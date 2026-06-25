"""table_predict — the bridge between the in-memory table workspace and SAP-RPT.

This is the single read → predict → mutate tool. Where ``table_query`` reads a
CSV into the shared ``TableStore`` and ``table_mutate`` writes columns back, this
tool closes the loop with a real tabular foundation model:

1. It reads a table that is already loaded in the run's shared workspace
   (``ctx["tables"]`` — the same dict ``table_query``/``table_mutate`` use).
2. It splits the rows on a target column: rows where the target is **filled**
   become in-context examples; rows where it is **empty/NaN** become the
   ``[PREDICT]`` queries.
3. It calls SAP-RPT (:class:`server.rpt.client.RPTClient`) to predict the
   missing cells, with confidence scores.
4. It **writes the predictions back** into the table as a versioned, audited
   mutation — so a downstream agent (a reviewer, the export step) sees the
   completed column immediately, exactly like a manual ``table_mutate``.

The agent therefore never has to shuttle JSON rows between ``table_query`` and
``rpt_predict`` by hand: it loads a CSV and asks for a column to be predicted.
``rpt_predict`` (raw JSON rows) and ``rpt_chat`` (natural language) remain
available for cases that are not backed by a loaded table.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from ..base import Tool
from .table import TableStore, _actor, _loaded_df, _resolve

logger = logging.getLogger(__name__)

# SAP-RPT in-context limits (mirrored from rpt_predict).
_MIN_CONTEXT_ROWS = 2
_MAX_QUERY_ROWS = 50
_DEFAULT_MAX_CONTEXT_ROWS = 256


class TablePredictInput(BaseModel):
    """Input schema for the table_predict tool."""

    target_column: str = Field(
        description=(
            "The column to predict. Rows where this column already has a value are "
            "used as in-context examples; rows where it is empty/blank are the ones "
            "predicted. The table must already be loaded (use the 'table_query' tool's "
            "action='load' first)."
        )
    )
    table_name: str | None = Field(
        default=None,
        description=(
            "Which loaded table to operate on. Defaults to the only loaded table, or "
            "the first one when several are loaded."
        ),
    )
    index_column: str | None = Field(
        default=None,
        description=(
            "Optional column that identifies each row (e.g. 'equipment_id'). Used only "
            "to label predictions in the response; it makes the output easier to read."
        ),
    )
    output_column: str | None = Field(
        default=None,
        description=(
            "Column to write the predictions into. Defaults to 'target_column' (fills "
            "the blanks in place). Give a different name to keep the original column and "
            "add the predictions alongside it."
        ),
    )
    max_context_rows: int = Field(
        default=_DEFAULT_MAX_CONTEXT_ROWS,
        description=(
            "Cap on how many filled rows are sent to the model as examples "
            f"(default {_DEFAULT_MAX_CONTEXT_ROWS}, hard max 2048). Lower it for very "
            "large tables to keep the request small."
        ),
    )


class TablePredictTool(Tool):
    """Predict a missing column on a loaded table via SAP-RPT and write it back.

    This unifies the coworkers' table tools with the SAP-RPT model: it reads the
    shared in-memory table, predicts the empty cells of ``target_column`` from the
    filled ones, and stores the result as a versioned mutation that downstream
    agents can see and audit.
    """

    name = "table_predict"
    description = (
        "Predict the empty cells of a column on a table that is already loaded in the "
        "workspace, using the SAP-RPT tabular foundation model, then write the "
        "predictions back into the table. Rows where 'target_column' is filled are the "
        "examples; rows where it is blank are predicted. The write is type-checked, "
        "versioned and visible to other agents (audit via table_query action='history'). "
        "Load the CSV with table_query action='load' first, then call this with the "
        "column to predict. Returns the predictions with SAP-RPT confidence scores; "
        "retrieve the completed CSV with table_query action='export'."
    )
    input_model = TablePredictInput

    async def execute(
        self, validated_input: BaseModel, context: dict[str, Any] | None = None
    ) -> str:
        if not isinstance(validated_input, TablePredictInput):
            return "Invalid input."
        inp = validated_input
        ctx = context or {}

        tables: dict[str, TableStore] | None = ctx.get("tables")
        if tables is None:
            return "Table workspace not available."

        store = _resolve(inp.table_name, tables)
        if store is None or store.df is None:
            return (
                "No table loaded. Use the 'table_query' tool's action='load' "
                "(or 'table_mutate' action='create') first."
            )

        df = _loaded_df(store)
        target = inp.target_column
        if target not in df.columns:
            cols = ", ".join(map(str, df.columns))
            return f"Column '{target}' not found. Available columns: {cols}"

        if inp.index_column and inp.index_column not in df.columns:
            cols = ", ".join(map(str, df.columns))
            return f"index_column '{inp.index_column}' not found. Available columns: {cols}"

        # Split rows: blank target -> query (predict), filled target -> context.
        blank = df[target].isna() | (df[target].astype(str).str.strip() == "")
        context_df = df[~blank]
        query_df = df[blank]

        n_context, n_query = len(context_df), len(query_df)
        if n_query == 0:
            return (
                f"Nothing to predict: every row already has a '{target}' value. Clear the "
                "cells you want predicted (leave them blank) before calling table_predict."
            )
        if n_context < _MIN_CONTEXT_ROWS:
            return (
                f"Only {n_context} example row(s) have a '{target}' value. SAP-RPT needs at "
                f"least {_MIN_CONTEXT_ROWS} filled rows to learn from."
            )
        if n_query > _MAX_QUERY_ROWS:
            return (
                f"{n_query} rows need predicting, but SAP-RPT predicts at most "
                f"{_MAX_QUERY_ROWS} at a time. Narrow the table (e.g. predict in batches) "
                "and try again."
            )

        cap = max(_MIN_CONTEXT_ROWS, min(inp.max_context_rows, 2048))
        if n_context > cap:
            context_df = context_df.head(cap)

        # Build the RPT payload. to_json handles NaN -> null and numpy -> native types.
        query_marked = query_df.copy()
        query_marked[target] = "[PREDICT]"
        context_rows = json.loads(context_df.to_json(orient="records"))
        query_rows = json.loads(query_marked.to_json(orient="records"))
        rows = context_rows + query_rows

        try:
            from server.rpt.client import RPTClient

            client = RPTClient()
            prediction = await client.predict(rows=rows, index_column=inp.index_column)
        except RuntimeError as exc:
            return f"RPT configuration error: {exc}"
        except Exception as exc:
            logger.exception("table_predict RPT call failed")
            return f"RPT prediction failed: {exc}"

        # Map predictions back to the query rows, in order.
        predicted: list[tuple[str, float | None]] = []
        for pred_row in prediction.rows:
            value = _pick_value(pred_row, target)
            if value is not None:
                predicted.append((value.prediction, value.confidence))

        if not predicted:
            return (
                "SAP-RPT returned no usable predictions for this table. The rows were sent "
                "successfully but the response contained no values for "
                f"'{target}'."
            )
        if len(predicted) != n_query:
            logger.warning(
                "table_predict: expected %d predictions, got %d", n_query, len(predicted)
            )

        # Write the completed column back: keep known values, fill blanks with predictions.
        output_col = inp.output_column or target
        numeric_target = pd.api.types.is_numeric_dtype(df[target])
        query_positions = list(query_df.index)

        new_column = _existing_base_column(df, target, output_col)
        applied = 0
        for pos, (pred_text, _conf) in zip(query_positions, predicted, strict=False):
            new_column[pos] = _coerce(pred_text, numeric_target)
            applied += 1

        async with store.lock:
            live = _loaded_df(store)
            if len(live) != len(new_column):
                return (
                    "The table changed while predicting (row count differs). Re-read it "
                    "with table_query and call table_predict again."
                )
            live[output_col] = [new_column[i] for i in live.index]
            verb = "wrote" if output_col == target else f"added '{output_col}' with"
            store.record(
                _actor(ctx),
                f"table_predict {verb} {applied} SAP-RPT prediction(s) for '{target}'",
            )
            version = store.version

        return _format(
            target=target,
            output_col=output_col,
            index_column=inp.index_column,
            query_df=query_df,
            predicted=predicted,
            prediction_id=prediction.id,
            version=version,
        )


def _pick_value(pred_row: Any, target: str) -> Any:
    """Pull the predicted value for ``target`` from one RPT response row.

    Falls back to the first predicted column if the model labelled it differently.
    """
    cols = pred_row.columns
    target_vals = cols.get(target)
    if target_vals:
        return target_vals[0]
    for values in cols.values():
        if values:
            return values[0]
    return None


def _existing_base_column(df: pd.DataFrame, target: str, output_col: str) -> dict[Any, Any]:
    """Base values for the output column, keyed by df index.

    When writing in place (or copying the target) the known cells are preserved;
    the caller overwrites the blank ones with predictions.
    """
    source = output_col if output_col in df.columns else target
    return dict(df[source].items())


def _coerce(text: str, numeric: bool) -> Any:
    """Best-effort cast of a predicted string to the target column's kind."""
    if not numeric:
        return text
    num = pd.to_numeric(text, errors="coerce")
    if pd.isna(num):
        return text
    # Keep ints int when the value is whole, else float.
    return int(num) if float(num).is_integer() else float(num)


def _format(
    *,
    target: str,
    output_col: str,
    index_column: str | None,
    query_df: pd.DataFrame,
    predicted: list[tuple[str, float | None]],
    prediction_id: str,
    version: int,
) -> str:
    lines = [
        f"## SAP-RPT predictions for '{target}' (id: {prediction_id})",
        "",
    ]
    labels = (
        [str(v) for v in query_df[index_column].tolist()]
        if index_column
        else [f"row {i}" for i in query_df.index]
    )
    confidences: list[float] = []
    for label, (value, conf) in zip(labels, predicted, strict=False):
        if conf is not None:
            confidences.append(conf)
            lines.append(f"- **{label}** → {value} (confidence: {conf:.2%})")
        else:
            lines.append(f"- **{label}** → {value} (confidence: not available)")

    target_note = "in place" if output_col == target else f"into new column '{output_col}'"
    lines.append("")
    lines.append(
        f"Wrote {len(predicted)} prediction(s) {target_note} — table is now version "
        f"{version}. Use table_query action='export' to retrieve the completed CSV."
    )

    if confidences:
        mean_conf = sum(confidences) / len(confidences)
        lines.append(
            f"\n---\n**Guidance for deliberation**: mean SAP-RPT confidence is "
            f"**{mean_conf:.2%}**. Calibrate your own conviction to this data-driven "
            "signal — a high confidence (>80%) is strong support for your position; a "
            "lower one warrants more caution."
        )
    return "\n".join(lines)
