import asyncio
from typing import Any

import pytest

from server.tools.base import Tool
from server.tools.builtin import table as table_module
from server.tools.builtin.table import (
    TableMutateInput,
    TableMutateTool,
    TableQueryInput,
    TableQueryTool,
    TableStore,
)

CSV = "city,population,prediction\nBerlin,3700000,\nMunich,1500000,\nHamburg,1900000,\n"


def _ctx(files: dict[str, str] | None = None) -> dict[str, Any]:
    """A fresh tool context with an empty shared table workspace."""
    return {"tables": {}, "files": files or {}}


def _first_store(ctx: dict[str, Any]) -> TableStore:
    """Return the first loaded store — used by assertion-heavy tests."""
    tables: dict[str, TableStore] = ctx["tables"]
    return next(iter(tables.values()))


async def _run(tool: Tool, ctx: dict[str, Any], **args: Any) -> str:
    result: str = await tool.execute(tool.input_model(**args), ctx)
    return result


@pytest.fixture()
def query() -> TableQueryTool:
    return TableQueryTool()


@pytest.fixture()
def mutate() -> TableMutateTool:
    return TableMutateTool()


# ── list ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_shows_attached_files(query: TableQueryTool) -> None:
    ctx = _ctx({"data.csv": CSV, "notes.txt": "hi"})
    out = await _run(query, ctx, action="list")
    assert "data.csv" in out
    assert "notes.txt" in out


@pytest.mark.asyncio
async def test_list_without_files(query: TableQueryTool) -> None:
    ctx = _ctx()
    out = await _run(query, ctx, action="list")
    assert "No files" in out


@pytest.mark.asyncio
async def test_list_shows_loaded_tables(query: TableQueryTool) -> None:
    ctx = _ctx({"data.csv": CSV})
    await _run(query, ctx, action="load", file_name="data.csv")
    out = await _run(query, ctx, action="list")
    assert "data.csv" in out
    assert "3 row(s)" in out


# ── load ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_load_from_inline_csv(query: TableQueryTool) -> None:
    ctx = _ctx()
    out = await _run(query, ctx, action="load", csv_text=CSV)
    assert "3 row(s)" in out
    assert "city" in out and "population" in out
    assert _first_store(ctx).df is not None


@pytest.mark.asyncio
async def test_load_from_attached_file(query: TableQueryTool) -> None:
    ctx = _ctx({"data.csv": CSV})
    out = await _run(query, ctx, action="load", file_name="data.csv")
    assert "3 row(s)" in out


@pytest.mark.asyncio
async def test_load_missing_file_lists_available(query: TableQueryTool) -> None:
    ctx = _ctx({"data.csv": CSV})
    out = await _run(query, ctx, action="load", file_name="nope.csv")
    assert "not found" in out
    assert "data.csv" in out


@pytest.mark.asyncio
async def test_load_requires_a_source(query: TableQueryTool) -> None:
    ctx = _ctx()
    out = await _run(query, ctx, action="load")
    assert "requires" in out


@pytest.mark.asyncio
async def test_load_keyed_by_file_name(query: TableQueryTool) -> None:
    ctx = _ctx({"data.csv": CSV})
    await _run(query, ctx, action="load", file_name="data.csv")
    assert "data.csv" in ctx["tables"]


@pytest.mark.asyncio
async def test_load_rejects_oversized_csv(
    query: TableQueryTool, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(table_module, "_MAX_TABLE_ROWS", 2)
    ctx = _ctx()
    out = await _run(query, ctx, action="load", csv_text=CSV)
    assert "exceeds the 2-row limit" in out
    assert _first_store(ctx).df is None


# ── create ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_empty_table(mutate: TableMutateTool) -> None:
    ctx = _ctx()
    out = await _run(mutate, ctx, action="create", columns=["name", "score"])
    assert "0 row(s)" in out
    assert list(_first_store(ctx).df.columns) == ["name", "score"]


@pytest.mark.asyncio
async def test_create_seeded_table_then_read(
    mutate: TableMutateTool, query: TableQueryTool
) -> None:
    ctx = _ctx()
    await _run(
        mutate,
        ctx,
        action="create",
        columns=["name", "score"],
        rows=[{"name": "a", "score": 1}, {"name": "b", "score": 2}],
    )
    out = await _run(query, ctx, action="read")
    assert "a" in out and "b" in out
    assert len(_first_store(ctx).df) == 2


@pytest.mark.asyncio
async def test_create_aligns_seed_to_declared_columns(mutate: TableMutateTool) -> None:
    ctx = _ctx()
    await _run(
        mutate,
        ctx,
        action="create",
        columns=["name", "score"],
        values={"name": "a", "extra": "ignored"},
    )
    assert list(_first_store(ctx).df.columns) == ["name", "score"]


@pytest.mark.asyncio
async def test_create_requires_columns(mutate: TableMutateTool) -> None:
    ctx = _ctx()
    out = await _run(mutate, ctx, action="create")
    assert "requires 'columns'" in out


@pytest.mark.asyncio
async def test_create_keyed_by_table_name(mutate: TableMutateTool) -> None:
    ctx = _ctx()
    await _run(mutate, ctx, action="create", columns=["x"], table_name="results")
    assert "results" in ctx["tables"]


@pytest.mark.asyncio
async def test_create_then_insert_and_add_column(mutate: TableMutateTool) -> None:
    ctx = _ctx()
    await _run(mutate, ctx, action="create", columns=["city"])
    await _run(mutate, ctx, action="insert", values={"city": "Berlin"})
    out = await _run(mutate, ctx, action="add_column", column="prediction", default=0)
    assert "column 'prediction'" in out
    assert _first_store(ctx).df["prediction"].tolist() == [0]


# ── guard: operating before load ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_query_actions_require_loaded_table(query: TableQueryTool) -> None:
    ctx = _ctx()
    out = await _run(query, ctx, action="describe")
    assert "No table loaded" in out


@pytest.mark.asyncio
async def test_mutate_actions_require_loaded_table(mutate: TableMutateTool) -> None:
    ctx = _ctx()
    out = await _run(mutate, ctx, action="insert", values={"city": "Berlin"})
    assert "No table loaded" in out


@pytest.mark.asyncio
async def test_query_missing_workspace_is_reported(query: TableQueryTool) -> None:
    out = await query.execute(TableQueryInput(action="describe"), {})
    assert "not available" in out


@pytest.mark.asyncio
async def test_mutate_missing_workspace_is_reported(mutate: TableMutateTool) -> None:
    out = await mutate.execute(TableMutateInput(action="create", columns=["x"]), {})
    assert "not available" in out


# ── describe / read ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_describe_reports_shape_columns_and_version(query: TableQueryTool) -> None:
    ctx = _ctx()
    await _run(query, ctx, action="load", csv_text=CSV)
    out = await _run(query, ctx, action="describe")
    assert "3 row(s)" in out
    assert "population" in out
    assert "version 1" in out


@pytest.mark.asyncio
async def test_read_filters_and_selects_columns(query: TableQueryTool) -> None:
    ctx = _ctx()
    await _run(query, ctx, action="load", csv_text=CSV)
    out = await _run(
        query, ctx, action="read", where={"city": "Munich"}, columns=["city", "population"]
    )
    assert "Munich" in out
    assert "Berlin" not in out
    assert "prediction" not in out


@pytest.mark.asyncio
async def test_read_no_match(query: TableQueryTool) -> None:
    ctx = _ctx()
    await _run(query, ctx, action="load", csv_text=CSV)
    out = await _run(query, ctx, action="read", where={"city": "Paris"})
    assert "No rows match" in out


@pytest.mark.asyncio
async def test_read_unknown_column(query: TableQueryTool) -> None:
    ctx = _ctx()
    await _run(query, ctx, action="load", csv_text=CSV)
    out = await _run(query, ctx, action="read", columns=["nope"])
    assert "Unknown column" in out


@pytest.mark.asyncio
async def test_read_unknown_filter_column_is_a_clean_error(query: TableQueryTool) -> None:
    ctx = _ctx()
    await _run(query, ctx, action="load", csv_text=CSV)
    out = await _run(query, ctx, action="read", where={"nope": "x"})
    assert out == "Unknown column: 'nope'"


# ── filter operators ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_read_supports_comparison_operators(query: TableQueryTool) -> None:
    ctx = _ctx()
    await _run(query, ctx, action="load", csv_text=CSV)
    out = await _run(query, ctx, action="read", where={"population": {"gt": 1700000}})
    assert "Berlin" in out and "Hamburg" in out
    assert "Munich" not in out


@pytest.mark.asyncio
async def test_read_supports_in_operator(query: TableQueryTool) -> None:
    ctx = _ctx()
    await _run(query, ctx, action="load", csv_text=CSV)
    out = await _run(query, ctx, action="read", where={"city": {"in": ["Berlin", "Munich"]}})
    assert "Berlin" in out and "Munich" in out
    assert "Hamburg" not in out


@pytest.mark.asyncio
async def test_read_supports_contains_operator(query: TableQueryTool) -> None:
    ctx = _ctx()
    await _run(query, ctx, action="load", csv_text=CSV)
    out = await _run(query, ctx, action="read", where={"city": {"contains": "burg"}})
    assert "Hamburg" in out
    assert "Berlin" not in out and "Munich" not in out


@pytest.mark.asyncio
async def test_read_rejects_unknown_operator(query: TableQueryTool) -> None:
    ctx = _ctx()
    await _run(query, ctx, action="load", csv_text=CSV)
    out = await _run(query, ctx, action="read", where={"population": {"between": [1, 2]}})
    assert "unknown filter operator 'between'" in out


@pytest.mark.asyncio
async def test_read_rejects_multi_operator_filter(query: TableQueryTool) -> None:
    ctx = _ctx()
    await _run(query, ctx, action="load", csv_text=CSV)
    out = await _run(query, ctx, action="read", where={"population": {"gt": 1, "lt": 2}})
    assert "exactly one operator" in out


# ── insert / update / delete ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_insert_appends_row(query: TableQueryTool, mutate: TableMutateTool) -> None:
    ctx = _ctx()
    await _run(query, ctx, action="load", csv_text=CSV)
    out = await _run(
        mutate, ctx, action="insert", values={"city": "Cologne", "population": 1100000}
    )
    assert "4 row(s)" in out
    assert len(_first_store(ctx).df) == 4


@pytest.mark.asyncio
async def test_insert_rejects_type_mismatch(query: TableQueryTool, mutate: TableMutateTool) -> None:
    ctx = _ctx()
    await _run(query, ctx, action="load", csv_text=CSV)
    out = await _run(mutate, ctx, action="insert", values={"city": "Cologne", "population": "lots"})
    assert "Type mismatch" in out
    assert "expected a number" in out
    # The bad row must not have been written.
    assert len(_first_store(ctx).df) == 3


@pytest.mark.asyncio
async def test_update_matching_rows(query: TableQueryTool, mutate: TableMutateTool) -> None:
    ctx = _ctx()
    await _run(query, ctx, action="load", csv_text=CSV)
    out = await _run(
        mutate, ctx, action="update", where={"city": "Berlin"}, values={"population": 4000000}
    )
    assert "Updated 1 row(s)" in out
    df = _first_store(ctx).df
    assert int(df.loc[df["city"] == "Berlin", "population"].iloc[0]) == 4000000


@pytest.mark.asyncio
async def test_update_rejects_type_mismatch(query: TableQueryTool, mutate: TableMutateTool) -> None:
    ctx = _ctx()
    await _run(query, ctx, action="load", csv_text=CSV)
    out = await _run(
        mutate, ctx, action="update", where={"city": "Berlin"}, values={"population": "huge"}
    )
    assert "Type mismatch" in out
    df = _first_store(ctx).df
    assert int(df.loc[df["city"] == "Berlin", "population"].iloc[0]) == 3700000


@pytest.mark.asyncio
async def test_update_requires_where_and_values(
    query: TableQueryTool, mutate: TableMutateTool
) -> None:
    ctx = _ctx()
    await _run(query, ctx, action="load", csv_text=CSV)
    assert "requires 'where'" in await _run(mutate, ctx, action="update", values={"population": 1})
    assert "requires 'values'" in await _run(mutate, ctx, action="update", where={"city": "Berlin"})


@pytest.mark.asyncio
async def test_delete_matching_rows(query: TableQueryTool, mutate: TableMutateTool) -> None:
    ctx = _ctx()
    await _run(query, ctx, action="load", csv_text=CSV)
    out = await _run(mutate, ctx, action="delete", where={"city": "Hamburg"})
    assert "Deleted 1 row(s)" in out
    assert "2 row(s) remain" in out
    assert "Hamburg" not in _first_store(ctx).df["city"].tolist()


@pytest.mark.asyncio
async def test_delete_refuses_without_where(query: TableQueryTool, mutate: TableMutateTool) -> None:
    ctx = _ctx()
    await _run(query, ctx, action="load", csv_text=CSV)
    out = await _run(mutate, ctx, action="delete")
    assert "refusing" in out
    assert len(_first_store(ctx).df) == 3


# ── add_column (the prediction seam) / export ────────────────────────────────────


@pytest.mark.asyncio
async def test_add_column_with_values_is_the_prediction_seam(
    query: TableQueryTool, mutate: TableMutateTool
) -> None:
    ctx = _ctx()
    await _run(query, ctx, action="load", csv_text="city\nBerlin\nMunich\n")
    out = await _run(
        mutate, ctx, action="add_column", column="prediction", column_values=[1.0, 0.0]
    )
    assert "Added column 'prediction'" in out
    assert _first_store(ctx).df["prediction"].tolist() == [1.0, 0.0]


@pytest.mark.asyncio
async def test_add_column_length_mismatch(query: TableQueryTool, mutate: TableMutateTool) -> None:
    ctx = _ctx()
    await _run(query, ctx, action="load", csv_text="city\nBerlin\nMunich\n")
    out = await _run(mutate, ctx, action="add_column", column="p", column_values=[1.0])
    assert "must match" in out


@pytest.mark.asyncio
async def test_add_column_overwrite_is_reported(
    query: TableQueryTool, mutate: TableMutateTool
) -> None:
    ctx = _ctx()
    await _run(query, ctx, action="load", csv_text=CSV)
    out = await _run(mutate, ctx, action="add_column", column="prediction", default=0)
    assert "Replaced column 'prediction'" in out


@pytest.mark.asyncio
async def test_export_round_trips_mutations(query: TableQueryTool, mutate: TableMutateTool) -> None:
    ctx = _ctx()
    await _run(query, ctx, action="load", csv_text="city\nBerlin\nMunich\n")
    await _run(mutate, ctx, action="add_column", column="prediction", column_values=[1, 0])
    out = await _run(query, ctx, action="export")
    assert out.splitlines()[0] == "city,prediction"
    assert "Berlin,1" in out


# ── audit trail / versioning ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_history_tracks_mutations_with_versions(
    query: TableQueryTool, mutate: TableMutateTool
) -> None:
    ctx = _ctx()
    await _run(query, ctx, action="load", csv_text=CSV)
    await _run(mutate, ctx, action="insert", values={"city": "Cologne", "population": 1100000})
    await _run(mutate, ctx, action="delete", where={"city": "Hamburg"})
    out = await _run(query, ctx, action="history")
    assert "Current version: 3" in out
    assert "v1" in out and "loaded" in out
    assert "v2" in out and "inserted" in out
    assert "v3" in out and "deleted" in out
    store = _first_store(ctx)
    assert store.version == 3


@pytest.mark.asyncio
async def test_history_reports_no_changes_for_fresh_table(query: TableQueryTool) -> None:
    ctx = _ctx()
    await _run(query, ctx, action="load", csv_text=CSV)
    out = await _run(query, ctx, action="history")
    assert "v1" in out and "loaded" in out


@pytest.mark.asyncio
async def test_history_caps_entries(query: TableQueryTool, mutate: TableMutateTool) -> None:
    ctx = _ctx()
    await _run(query, ctx, action="load", csv_text="city\nBerlin\n")
    for i in range(table_module._MAX_HISTORY_ENTRIES + 5):
        await _run(mutate, ctx, action="insert", values={"city": f"city{i}"})
    store = _first_store(ctx)
    assert len(store.history) == table_module._MAX_HISTORY_ENTRIES
    assert store.version == table_module._MAX_HISTORY_ENTRIES + 5 + 1


# ── concurrency: per-store lock keeps mutations consistent ───────────────────────


@pytest.mark.asyncio
async def test_concurrent_inserts_are_serialised_by_the_lock(
    query: TableQueryTool, mutate: TableMutateTool
) -> None:
    ctx = _ctx()
    await _run(query, ctx, action="load", csv_text="city\nBerlin\n")
    await asyncio.gather(
        *(_run(mutate, ctx, action="insert", values={"city": f"agent-{i}"}) for i in range(10))
    )
    store = _first_store(ctx)
    assert len(store.df) == 11
    # Every insert must have bumped the version exactly once — no lost updates.
    assert store.version == 11


# ── error sanitisation ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_internal_errors_do_not_leak_exception_internals(
    query: TableQueryTool, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _ctx()
    await _run(query, ctx, action="load", csv_text=CSV)

    def _boom(_df: Any) -> Any:
        raise RuntimeError("pandas.core.internals.blocks: secret stack detail")

    monkeypatch.setattr(table_module, "_describe", _boom)
    out = await _run(query, ctx, action="describe")
    assert out == "Table operation failed due to an internal error."
    assert "pandas.core.internals" not in out


# ── shared workspace: mutations visible across agent calls ───────────────────────


@pytest.mark.asyncio
async def test_store_persists_across_calls(query: TableQueryTool, mutate: TableMutateTool) -> None:
    ctx = _ctx()
    await _run(query, ctx, action="load", csv_text=CSV)
    await _run(mutate, ctx, action="delete", where={"city": "Berlin"})
    await _run(mutate, ctx, action="insert", values={"city": "Cologne", "population": 1100000})
    out = await _run(query, ctx, action="read")
    assert "Berlin" not in out
    assert "Cologne" in out


@pytest.mark.asyncio
async def test_two_agents_share_workspace(query: TableQueryTool, mutate: TableMutateTool) -> None:
    """Mutations by the first agent call are visible to the second — the shared
    dict is the cross-agent persistence mechanism."""
    shared: dict[str, TableStore] = {}
    ctx_a = {"tables": shared, "files": {"data.csv": CSV}, "agent_id": "agent-a"}
    ctx_b = {"tables": shared, "files": {"data.csv": CSV}, "agent_id": "agent-b"}

    # Agent A loads and predicts.
    await _run(query, ctx_a, action="load", file_name="data.csv")
    await _run(mutate, ctx_a, action="add_column", column="score", default=1)

    # Agent B sees Agent A's prediction column without reloading.
    out = await _run(query, ctx_b, action="describe")
    assert "score" in out

    # ...and the audit trail names the actor who made the change.
    history = await _run(query, ctx_b, action="history")
    assert "agent-a" in history


@pytest.mark.asyncio
async def test_table_name_selects_specific_store(
    query: TableQueryTool, mutate: TableMutateTool
) -> None:
    ctx = _ctx()
    await _run(mutate, ctx, action="create", columns=["x"], table_name="alpha")
    await _run(mutate, ctx, action="create", columns=["y"], table_name="beta")
    out_a = await _run(query, ctx, action="describe", table_name="alpha")
    out_b = await _run(query, ctx, action="describe", table_name="beta")
    assert "x (object)" in out_a and "y (object)" not in out_a
    assert "y (object)" in out_b and "x (object)" not in out_b
