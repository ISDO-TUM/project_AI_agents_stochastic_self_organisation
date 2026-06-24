"""RPT Chat tool — natural language interface to SAP-RPT predictions.

Agents call this tool to ask questions about tabular data in natural language.
Chat-RPT supports what-if analysis, add-row predictions, accuracy testing,
and data questions — all without manually constructing prediction requests.

This is a higher-level complement to ``rpt_predict``: while ``rpt_predict``
requires the agent to construct explicit context/query rows, ``rpt_chat``
lets the agent describe what it wants in plain English and the RPT system
handles intent classification and query construction automatically.

Example agent interaction::

    Agent calls rpt_chat with:
        question: "What if I reduce the quantity by 20%, how would CO2 emissions change?"
        table_context: '{"columns": ["OrderID", "Quantity", "CO2"], "rowCount": 150, ...}'

    Tool returns:
        Reducing quantity by 20% across all orders is predicted to decrease
        CO2 emissions by approximately 15%, from 2,400 kg to 2,040 kg on average.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from ..base import Tool

logger = logging.getLogger(__name__)


class RPTChatInput(BaseModel):
    """Input schema for the RPT Chat tool."""

    question: str = Field(
        description=(
            "A natural language question about your data. Supports: "
            "what-if analysis ('What if I change supplier to X?'), "
            "add-row predictions ('New order: quantity 500, predict cost'), "
            "accuracy testing ('Test accuracy for revenue column'), "
            "and data questions ('What is the average cost by region?')."
        )
    )
    table_context: str | None = Field(
        default=None,
        description=(
            "Optional JSON object with dataset metadata. Required for prediction "
            "queries. Include: columns (string array), rowCount (number), "
            "sampleRows (array of objects, up to 5), and columnStats (array of "
            "objects with column, type, and stats like min/max/avg or uniqueCount). "
            "Example: "
            '{"columns": ["ID", "Qty", "Cost"], "rowCount": 100, '
            '"sampleRows": [{"ID": "1", "Qty": 50, "Cost": 1200}], '
            '"columnStats": [{"column": "Qty", "type": "numeric", "min": 10, "max": 500}]}'
        ),
    )
    conversation_context: str | None = Field(
        default=None,
        description=(
            "Optional JSON object with context from a previous RPT Chat turn. "
            "Include lastIntent and lastQueryParams for follow-up queries."
        ),
    )


class RPTChatTool(Tool):
    """Ask natural language questions about tabular data via Chat-RPT.

    Use this for what-if analysis, add-row predictions, accuracy testing,
    and data questions. For precise control over prediction rows, use
    rpt_predict instead.
    """

    name = "rpt_chat"
    description = (
        "Ask natural language questions about tabular data using Chat-RPT. "
        "Supports what-if analysis ('What if supplier changes to X?'), "
        "adding hypothetical rows and predicting outcomes, testing model accuracy, "
        "and data aggregation questions. Provide dataset metadata via table_context "
        "for prediction-related queries. Use this when you want to explore data "
        "scenarios without manually constructing prediction rows."
    )
    input_model = RPTChatInput

    async def execute(
        self, validated_input: BaseModel, context: dict[str, Any] | None = None
    ) -> str:
        if not isinstance(validated_input, RPTChatInput):
            return "Invalid input."

        inp = validated_input

        if not inp.question.strip():
            return "Please provide a non-empty question about the data."

        # Parse optional table_context
        table_context: dict[str, Any] | None = None
        if inp.table_context:
            try:
                table_context = json.loads(inp.table_context)
            except json.JSONDecodeError as exc:
                return f"Invalid JSON in 'table_context': {exc}."

        # Parse optional conversation_context
        conversation_context: dict[str, Any] | None = None
        if inp.conversation_context:
            try:
                conversation_context = json.loads(inp.conversation_context)
            except json.JSONDecodeError as exc:
                return f"Invalid JSON in 'conversation_context': {exc}."

        # Build messages
        messages = [{"role": "user", "content": inp.question}]

        # Call the RPT Chat API
        try:
            from server.rpt.client import RPTClient

            client = RPTClient()
            response = await client.chat(
                messages=messages,
                table_context=table_context,
                conversation_context=conversation_context,
            )
        except RuntimeError as exc:
            return f"RPT configuration error: {exc}"
        except Exception as exc:
            logger.exception("RPT chat call failed")
            return f"RPT chat failed: {exc}"

        # Format the response
        lines: list[str] = [
            "## RPT Analysis",
            "",
            response.content,
        ]

        if response.intent:
            lines.append(f"\n*Analysis type: {response.intent}*")

        if response.suggestions:
            lines.append("\n**Suggested follow-ups:**")
            for suggestion in response.suggestions:
                label = suggestion.get("label", "")
                query = suggestion.get("query", "")
                lines.append(f'- {label}: "{query}"')

        return "\n".join(lines)
