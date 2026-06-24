"""Tests for the table_predict bridge tool.

table_predict ties the in-memory table workspace (table_query/table_mutate) to
SAP-RPT: it reads a loaded table, predicts a blank column, and writes the result
back. These tests mock ``RPTClient.predict`` so they never hit the real API and
focus on the bridge logic: row splitting, write-back, type coercion, and the
guard rails (missing column, nothing to predict, too few examples).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from server.rpt.client import RPTPrediction, RPTPredictionRow, RPTPredictionValue
from server.tools.base import Tool
from server.tools.builtin.table import TableQueryTool, TableStore
from server.tools.builtin.table_predict import TablePredictTool

# E008/E009/E010 have a blank rul_days -> they are the rows to predict.
CSV = (
    "equipment_id,operating_hours,vibration,rul_days\n"
    "E001,8500,2.1,120\n"
    "E002,12000,4.8,30\n"
    "E003,6200,1.5,210\n"
    "E008,9200,3.5,\n"
    "E009,13500,5.0,\n"
    "E010,7000,1.9,\n"
)


def _ctx() -> dict[str, Any]:
    return {"tables": {}, "files": {"equipment.csv": CSV}, "agent_id": "analyst"}


def _store(ctx: dict[str, Any]) -> TableStore:
    return next(iter(ctx["tables"].values()))


async def _run(tool: Tool, ctx: dict[str, Any], **args: Any) -> str:
    return str(await tool.execute(tool.input_model(**args), ctx))


def _fake_prediction(values: list[tuple[str, str, float | None]]) -> RPTPrediction:
    """Build an RPTPrediction as RPTClient.predict would return it.

    ``values`` is (index_value, predicted_rul_days, confidence) per query row.
    """
    rows = [
        RPTPredictionRow(
            index_value=idx,
            columns={"rul_days": [RPTPredictionValue(prediction=pred, confidence=conf)]},
        )
        for idx, pred, conf in values
    ]
    return RPTPrediction(
        id="pred-test",
        rows=rows,
        num_predict_rows=len(rows),
        num_predict_tokens=len(rows),
        delay_ms=1.0,
    )


async def _load(ctx: dict[str, Any]) -> None:
    await _run(TableQueryTool(), ctx, action="load", file_name="equipment.csv")


@pytest.mark.asyncio
async def test_predicts_blank_rows_and_writes_back() -> None:
    ctx = _ctx()
    await _load(ctx)
    prediction = _fake_prediction(
        [("E008", "55", 0.91), ("E009", "20", 0.84), ("E010", "180", 0.6)]
    )

    with (
        patch.dict("os.environ", {"SAP_RPT_API_KEY": "test-key"}),
        patch("server.rpt.client.RPTClient.predict", new=AsyncMock(return_value=prediction)),
    ):
        out = await _run(
            TablePredictTool(),
            ctx,
            target_column="rul_days",
            index_column="equipment_id",
        )

    # The response surfaces predictions and confidence per machine.
    assert "E008" in out and "55" in out
    assert "91" in out  # confidence percentage of E008
    assert "version" in out

    # The blanks were filled in place, coerced to int, and the known rows untouched.
    df = _store(ctx).df
    assert df is not None
    by_id = df.set_index("equipment_id")["rul_days"].to_dict()
    assert by_id["E008"] == 55
    assert by_id["E009"] == 20
    assert by_id["E010"] == 180
    assert by_id["E001"] == 120  # context row unchanged


@pytest.mark.asyncio
async def test_output_column_keeps_original() -> None:
    ctx = _ctx()
    await _load(ctx)
    prediction = _fake_prediction([("E008", "55", 0.9), ("E009", "20", 0.9), ("E010", "180", 0.9)])

    with (
        patch.dict("os.environ", {"SAP_RPT_API_KEY": "test-key"}),
        patch("server.rpt.client.RPTClient.predict", new=AsyncMock(return_value=prediction)),
    ):
        out = await _run(
            TablePredictTool(),
            ctx,
            target_column="rul_days",
            output_column="rul_days_pred",
        )

    df = _store(ctx).df
    assert df is not None
    assert "rul_days_pred" in df.columns
    # Original column still has its blanks; the new column holds the predictions.
    pred_by_id = df.set_index("equipment_id")["rul_days_pred"].to_dict()
    assert pred_by_id["E008"] == 55
    assert "rul_days_pred" in out


@pytest.mark.asyncio
async def test_records_audit_history() -> None:
    ctx = _ctx()
    await _load(ctx)
    prediction = _fake_prediction([("E008", "55", 0.9), ("E009", "20", 0.9), ("E010", "180", 0.9)])
    version_before = _store(ctx).version

    with (
        patch.dict("os.environ", {"SAP_RPT_API_KEY": "test-key"}),
        patch("server.rpt.client.RPTClient.predict", new=AsyncMock(return_value=prediction)),
    ):
        await _run(TablePredictTool(), ctx, target_column="rul_days")

    store = _store(ctx)
    assert store.version == version_before + 1
    assert any("table_predict" in entry for entry in store.history)


@pytest.mark.asyncio
async def test_missing_column_is_reported() -> None:
    ctx = _ctx()
    await _load(ctx)
    out = await _run(TablePredictTool(), ctx, target_column="nonexistent")
    assert "not found" in out.lower()


@pytest.mark.asyncio
async def test_nothing_to_predict_when_column_full() -> None:
    ctx = _ctx()
    await _load(ctx)
    # operating_hours is fully populated -> no blank rows to predict.
    out = await _run(TablePredictTool(), ctx, target_column="operating_hours")
    assert "nothing to predict" in out.lower()


@pytest.mark.asyncio
async def test_no_table_loaded() -> None:
    ctx = _ctx()
    out = await _run(TablePredictTool(), ctx, target_column="rul_days")
    assert "no table loaded" in out.lower()


@pytest.mark.asyncio
async def test_too_few_examples() -> None:
    ctx = {"tables": {}, "files": {}, "agent_id": "a"}
    # Only one filled row, two blanks -> not enough context for SAP-RPT.
    csv = "id,x,y\nA,1,10\nB,2,\nC,3,\n"
    await _run(TableQueryTool(), ctx, action="load", csv_text=csv, table_name="t")
    out = await _run(TablePredictTool(), ctx, target_column="y")
    assert "at least" in out.lower()
