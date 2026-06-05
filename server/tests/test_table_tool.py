from typing import Any

import pytest

from server.tools.builtin.table import TableInput, TableStore, TableTool

CSV = "city,population,prediction\nBerlin,3700000,\nMunich,1500000,\nHamburg,1900000,\n"


def _ctx(files: dict[str, str] | None = None) -> dict[str, Any]:
    """A fresh tool context with an empty table workspace, like the simulation builds."""
    return {"table": TableStore(), "files": files or {}}


async def _run(tool: TableTool, ctx: dict[str, Any], **args: Any) -> str:
    result: str = await tool.execute(TableInput(**args), ctx)
    return result


# ── list ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_shows_attached_files() -> None:
    tool, ctx = TableTool(), _ctx({"data.csv": CSV, "notes.txt": "hi"})
    out = await _run(tool, ctx, action="list")
    assert "data.csv" in out
    assert "notes.txt" in out


@pytest.mark.asyncio
async def test_list_without_files() -> None:
    tool, ctx = TableTool(), _ctx()
    out = await _run(tool, ctx, action="list")
    assert "No files" in out


# ── load ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_load_from_inline_csv() -> None:
    tool, ctx = TableTool(), _ctx()
    out = await _run(tool, ctx, action="load", csv_text=CSV)
    assert "3 row(s)" in out
    assert "city" in out and "population" in out
    assert ctx["table"].df is not None


@pytest.mark.asyncio
async def test_load_from_attached_file() -> None:
    tool, ctx = TableTool(), _ctx({"data.csv": CSV})
    out = await _run(tool, ctx, action="load", file_name="data.csv")
    assert "3 row(s)" in out


@pytest.mark.asyncio
async def test_load_missing_file_lists_available() -> None:
    tool, ctx = TableTool(), _ctx({"data.csv": CSV})
    out = await _run(tool, ctx, action="load", file_name="nope.csv")
    assert "not found" in out
    assert "data.csv" in out


@pytest.mark.asyncio
async def test_load_requires_a_source() -> None:
    tool, ctx = TableTool(), _ctx()
    out = await _run(tool, ctx, action="load")
    assert "requires" in out


# ── create ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_empty_table() -> None:
    tool, ctx = TableTool(), _ctx()
    out = await _run(tool, ctx, action="create", columns=["name", "score"])
    assert "0 row(s)" in out
    assert list(ctx["table"].df.columns) == ["name", "score"]


@pytest.mark.asyncio
async def test_create_seeded_table_then_read() -> None:
    tool, ctx = TableTool(), _ctx()
    await _run(
        tool,
        ctx,
        action="create",
        columns=["name", "score"],
        rows=[{"name": "a", "score": 1}, {"name": "b", "score": 2}],
    )
    out = await _run(tool, ctx, action="read")
    assert "a" in out and "b" in out
    assert len(ctx["table"].df) == 2


@pytest.mark.asyncio
async def test_create_aligns_seed_to_declared_columns() -> None:
    tool, ctx = TableTool(), _ctx()
    # 'extra' is dropped; missing 'score' becomes NaN — schema is exactly `columns`.
    await _run(
        tool,
        ctx,
        action="create",
        columns=["name", "score"],
        values={"name": "a", "extra": "ignored"},
    )
    assert list(ctx["table"].df.columns) == ["name", "score"]


@pytest.mark.asyncio
async def test_create_requires_columns() -> None:
    tool, ctx = TableTool(), _ctx()
    out = await _run(tool, ctx, action="create")
    assert "requires 'columns'" in out


@pytest.mark.asyncio
async def test_create_then_insert_and_add_column() -> None:
    tool, ctx = TableTool(), _ctx()
    await _run(tool, ctx, action="create", columns=["city"])
    await _run(tool, ctx, action="insert", values={"city": "Berlin"})
    out = await _run(tool, ctx, action="add_column", column="prediction", default=0)
    assert "column 'prediction'" in out
    assert ctx["table"].df["prediction"].tolist() == [0]


# ── guard: operating before load ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_actions_require_loaded_table() -> None:
    tool, ctx = TableTool(), _ctx()
    out = await _run(tool, ctx, action="describe")
    assert "No table loaded" in out


@pytest.mark.asyncio
async def test_missing_workspace_is_reported() -> None:
    out = await TableTool().execute(TableInput(action="describe"), {})
    assert "not available" in out


# ── describe / read ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_describe_reports_shape_and_columns() -> None:
    tool, ctx = TableTool(), _ctx()
    await _run(tool, ctx, action="load", csv_text=CSV)
    out = await _run(tool, ctx, action="describe")
    assert "3 row(s)" in out
    assert "population" in out


@pytest.mark.asyncio
async def test_read_filters_and_selects_columns() -> None:
    tool, ctx = TableTool(), _ctx()
    await _run(tool, ctx, action="load", csv_text=CSV)
    out = await _run(
        tool, ctx, action="read", where={"city": "Munich"}, columns=["city", "population"]
    )
    assert "Munich" in out
    assert "Berlin" not in out
    assert "prediction" not in out


@pytest.mark.asyncio
async def test_read_no_match() -> None:
    tool, ctx = TableTool(), _ctx()
    await _run(tool, ctx, action="load", csv_text=CSV)
    out = await _run(tool, ctx, action="read", where={"city": "Paris"})
    assert "No rows match" in out


@pytest.mark.asyncio
async def test_read_unknown_column() -> None:
    tool, ctx = TableTool(), _ctx()
    await _run(tool, ctx, action="load", csv_text=CSV)
    out = await _run(tool, ctx, action="read", columns=["nope"])
    assert "Unknown column" in out


# ── insert / update / delete ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_insert_appends_row() -> None:
    tool, ctx = TableTool(), _ctx()
    await _run(tool, ctx, action="load", csv_text=CSV)
    out = await _run(tool, ctx, action="insert", values={"city": "Cologne", "population": 1100000})
    assert "4 row(s)" in out
    assert len(ctx["table"].df) == 4


@pytest.mark.asyncio
async def test_update_matching_rows() -> None:
    tool, ctx = TableTool(), _ctx()
    await _run(tool, ctx, action="load", csv_text=CSV)
    out = await _run(
        tool, ctx, action="update", where={"city": "Berlin"}, values={"population": 4000000}
    )
    assert "Updated 1 row(s)" in out
    df = ctx["table"].df
    assert int(df.loc[df["city"] == "Berlin", "population"].iloc[0]) == 4000000


@pytest.mark.asyncio
async def test_update_requires_where_and_values() -> None:
    tool, ctx = TableTool(), _ctx()
    await _run(tool, ctx, action="load", csv_text=CSV)
    assert "requires 'where'" in await _run(tool, ctx, action="update", values={"population": 1})
    assert "requires 'values'" in await _run(tool, ctx, action="update", where={"city": "Berlin"})


@pytest.mark.asyncio
async def test_delete_matching_rows() -> None:
    tool, ctx = TableTool(), _ctx()
    await _run(tool, ctx, action="load", csv_text=CSV)
    out = await _run(tool, ctx, action="delete", where={"city": "Hamburg"})
    assert "Deleted 1 row(s)" in out
    assert "2 row(s) remain" in out
    assert "Hamburg" not in ctx["table"].df["city"].tolist()


@pytest.mark.asyncio
async def test_delete_refuses_without_where() -> None:
    tool, ctx = TableTool(), _ctx()
    await _run(tool, ctx, action="load", csv_text=CSV)
    out = await _run(tool, ctx, action="delete")
    assert "refusing" in out
    assert len(ctx["table"].df) == 3


# ── add_column (the prediction seam) / export ────────────────────────────────────


@pytest.mark.asyncio
async def test_add_column_with_values_is_the_prediction_seam() -> None:
    tool, ctx = TableTool(), _ctx()
    await _run(tool, ctx, action="load", csv_text="city\nBerlin\nMunich\n")
    out = await _run(tool, ctx, action="add_column", column="prediction", column_values=[1.0, 0.0])
    assert "Added column 'prediction'" in out
    assert ctx["table"].df["prediction"].tolist() == [1.0, 0.0]


@pytest.mark.asyncio
async def test_add_column_length_mismatch() -> None:
    tool, ctx = TableTool(), _ctx()
    await _run(tool, ctx, action="load", csv_text="city\nBerlin\nMunich\n")
    out = await _run(tool, ctx, action="add_column", column="p", column_values=[1.0])
    assert "must match" in out


@pytest.mark.asyncio
async def test_add_column_overwrite_is_reported() -> None:
    tool, ctx = TableTool(), _ctx()
    await _run(tool, ctx, action="load", csv_text=CSV)
    out = await _run(tool, ctx, action="add_column", column="prediction", default=0)
    assert "Replaced column 'prediction'" in out


@pytest.mark.asyncio
async def test_export_round_trips_mutations() -> None:
    tool, ctx = TableTool(), _ctx()
    await _run(tool, ctx, action="load", csv_text="city\nBerlin\nMunich\n")
    await _run(tool, ctx, action="add_column", column="prediction", column_values=[1, 0])
    out = await _run(tool, ctx, action="export")
    assert out.splitlines()[0] == "city,prediction"
    assert "Berlin,1" in out


# ── mutations persist across calls (RegistryIndex-style lifecycle) ───────────────


@pytest.mark.asyncio
async def test_store_persists_across_calls() -> None:
    tool, ctx = TableTool(), _ctx()
    await _run(tool, ctx, action="load", csv_text=CSV)
    await _run(tool, ctx, action="delete", where={"city": "Berlin"})
    await _run(tool, ctx, action="insert", values={"city": "Cologne", "population": 1100000})
    out = await _run(tool, ctx, action="read")
    assert "Berlin" not in out
    assert "Cologne" in out
