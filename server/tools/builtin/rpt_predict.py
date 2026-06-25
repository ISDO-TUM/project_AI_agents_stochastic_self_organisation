"""RPT Predict tool — tabular prediction via SAP-RPT in-context learning.

Agents call this tool to get data-driven predictions with confidence scores
from the SAP-RPT foundation model. The predictions are returned in a
structured format that agents can reference in their reasoning, and the
confidence scores can be used to calibrate the agent's own deliberation
confidence in the stochastic consensus system.

Example agent interaction::

    Agent calls rpt_predict with:
        action: "predict"
        rows: [
            {"equipment_id": "E001", "operating_hours": 8500, "vibration": 2.1, "rul_days": 120},
            {"equipment_id": "E002", "operating_hours": 12000, "vibration": 4.8, "rul_days": 30},
            {"equipment_id": "E003", "operating_hours": 9200, "rul_days": "[PREDICT]"}
        ]
        index_column: "equipment_id"
        target_columns: ["rul_days"]

    Tool returns:
        ## RPT Prediction Results
        ### E003
        - **rul_days**: 45 (confidence: 82.00%)
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from ..base import Tool

logger = logging.getLogger(__name__)


class RPTPredictInput(BaseModel):
    """Input schema for the RPT Predict tool."""

    rows: str = Field(
        description=(
            "JSON array of data rows. Each row is an object with column names as keys. "
            "Context rows have complete data (used as examples). "
            "Query rows contain '[PREDICT]' as the value for columns you want predicted. "
            "Minimum 2 context rows, maximum 2048. Minimum 1 query row, maximum 50. "
            "Example: "
            '[{"id": "E001", "hours": 8500, "rul": 120}, '
            '{"id": "E002", "hours": 9200, "rul": "[PREDICT]"}]'
        )
    )
    index_column: str | None = Field(
        default=None,
        description=(
            "Optional column name to use as row identifier in the response "
            "(e.g. 'equipment_id', 'customer_id'). Makes predictions easier to reference."
        ),
    )


class RPTPredictTool(Tool):
    """Run tabular predictions via SAP-RPT in-context learning.

    Use this tool to predict missing values in structured/tabular data.
    Provide example rows (context) and rows with [PREDICT] placeholders.
    The model learns patterns from the examples and predicts the missing values.

    The response includes prediction values AND confidence scores that you
    should factor into your reasoning and deliberation confidence.
    """

    name = "rpt_predict"
    description = (
        "Run tabular predictions using SAP-RPT (Relational Pretrained Transformer). "
        "Provide example rows (context) with known values and query rows with "
        "'[PREDICT]' placeholders. The model predicts missing values with confidence "
        "scores. Use this to ground your position in data-driven predictions. "
        "The confidence scores from the model should influence how confident you are "
        "in your overall position during deliberation."
    )
    input_model = RPTPredictInput

    async def execute(
        self, validated_input: BaseModel, context: dict[str, Any] | None = None
    ) -> str:
        if not isinstance(validated_input, RPTPredictInput):
            return "Invalid input."

        inp = validated_input

        # Parse the rows JSON
        try:
            rows = json.loads(inp.rows)
        except json.JSONDecodeError as exc:
            return f"Invalid JSON in 'rows': {exc}. Please provide a valid JSON array of objects."

        if not isinstance(rows, list) or not rows:
            return "The 'rows' field must be a non-empty JSON array of objects."

        # Validate row structure
        predict_rows = 0
        context_rows = 0
        for row in rows:
            if not isinstance(row, dict):
                return "Each row must be a JSON object with column names as keys."
            has_predict = any(str(v) == "[PREDICT]" for v in row.values())
            if has_predict:
                predict_rows += 1
            else:
                context_rows += 1

        if predict_rows == 0:
            return (
                "No query rows found. At least one row must contain '[PREDICT]' "
                "as a value for the column(s) you want predicted."
            )
        if context_rows < 2:
            return (
                f"Only {context_rows} context row(s) provided. "
                "SAP-RPT requires at least 2 context rows (rows without [PREDICT]) "
                "as examples for the model to learn from."
            )

        # Call the RPT API
        try:
            from server.rpt.client import RPTClient

            client = RPTClient()
            prediction = await client.predict(
                rows=rows,
                index_column=inp.index_column,
            )
        except RuntimeError as exc:
            return f"RPT configuration error: {exc}"
        except Exception as exc:
            logger.exception("RPT predict call failed")
            return f"RPT prediction failed: {exc}"

        # Format the response for the agent
        formatted: str = RPTClient.format_predictions(prediction)

        # Add confidence guidance for the agent
        mean_conf = RPTClient.extract_mean_confidence(prediction)
        if mean_conf is not None:
            formatted += (
                f"\n---\n"
                f"**Guidance for deliberation**: The RPT model's mean prediction "
                f"confidence is **{mean_conf:.2%}**. Consider calibrating your own "
                f"deliberation confidence based on this data-driven signal. "
                f"A high RPT confidence (>80%) suggests strong data support for "
                f"your position; a lower confidence suggests more uncertainty."
            )
        else:
            formatted += (
                "\n---\n"
                "**Note**: No confidence scores were returned by the model. "
                "The predictions are still valid but confidence-based calibration "
                "is not available for this dataset."
            )

        return formatted
