"""Tabular CRUD tools — read-only inspection and mutation, split for safety.

The tools manage an in-memory workspace of named ``TableStore`` objects. A
``TableStore`` is created on first ``load`` or ``create`` and keyed by the file
name (or an explicit ``table_name``). Because the same ``tables`` dict is
shared across every agent call in a run, mutations made by one agent are
immediately visible to the next — a predictor can add a column and a reviewer
downstream can inspect it without re-loading the file.

Two tools share this workspace:

- ``table_query`` (read-only: list/load/describe/read/export/history) — safe to
  hand to any agent that only needs to see the data.
- ``table_mutate`` (create/insert/update/delete/add_column) — reserved for
  agents that are meant to write (e.g. a predictor attaching a column).

Splitting the CRUD surface this way keeps each tool's schema small (an LLM
picks the right action *and* the right field subset more reliably from a
focused list) and gives the agent designer a real permission boundary: a
read-only reviewer simply never gets a tool that can mutate shared state.

Each ``TableStore`` carries a monotonic ``version`` and an audit ``history`` —
``table_query`` action='history' lets any agent check who changed what before
trusting potentially-stale data. A per-store ``asyncio.Lock`` makes that
safety property structural: the dispatch logic never awaits mid-mutation today
(so cooperative scheduling alone keeps it atomic), but the lock guarantees
that holds even if a future change — e.g. persisting the audit trail to a DB —
introduces an await inside a read-modify-write sequence.

CSV parsing is the only format-specific boundary; an Excel reader would slot in
alongside ``load_csv`` without touching any CRUD logic.
"""

from __future__ import annotations

import asyncio
import io
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, Field

from ..base import Tool

_MAX_DISPLAY_ROWS = 50
_SAMPLE_ROWS = 5
_MAX_TABLE_ROWS = 50_000
_MAX_HISTORY_ENTRIES = 20


@dataclass
class TableStore:
    """In-memory workspace for one table, shared across agent calls in a run."""

    df: pd.DataFrame | None = None
    version: int = 0
    history: list[str] = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def load_csv(self, text: str) -> None:
        df = pd.read_csv(io.StringIO(text))
        _check_row_cap(len(df))
        self.df = df

    def to_csv(self) -> str:
        return "" if self.df is None else str(self.df.to_csv(index=False))

    def record(self, actor: str, summary: str) -> None:
        """Bump the version and append an audit entry. Caller must hold `lock`."""
        self.version += 1
        self.history.append(f"v{self.version} — {actor}: {summary}")
        if len(self.history) > _MAX_HISTORY_ENTRIES:
            self.history = self.history[-_MAX_HISTORY_ENTRIES:]


def _check_row_cap(n: int) -> None:
    if n > _MAX_TABLE_ROWS:
        raise ValueError(
            f"{n} row(s) exceeds the {_MAX_TABLE_ROWS}-row limit for an in-memory table."
        )


def _loaded_df(store: TableStore) -> pd.DataFrame:
    """Narrow `store.df` to a DataFrame. Callers must have already checked
    ``store.df is not None`` (the dispatch layer reports "No table loaded"
    before reaching here) — this just gives mypy the same guarantee without
    an `assert`, which bandit flags as strippable-under-`-O`."""
    if store.df is None:
        raise RuntimeError("table store has no loaded DataFrame")
    return store.df


# ── filters ───────────────────────────────────────────────────────────────────
#
# `where` accepts either a literal (equality, the original behaviour) or a
# single-key operator object, e.g. {"population": {"gt": 1000000}}. This lets
# agents express ranges and set-membership without inventing a query language.

_FILTER_OPS = frozenset({"gt", "gte", "lt", "lte", "ne", "in", "contains"})


def _apply_op(series: pd.Series, op: str, val: Any) -> pd.Series:
    if op == "gt":
        return series > val
    if op == "gte":
        return series >= val
    if op == "lt":
        return series < val
    if op == "lte":
        return series <= val
    if op == "ne":
        return series != val
    if op == "in":
        return series.isin(val if isinstance(val, list) else [val])
    return series.astype(str).str.contains(str(val), case=False, na=False, regex=False)


def _mask(df: pd.DataFrame, where: dict[str, Any]) -> pd.Series:
    selected = pd.Series(True, index=df.index)
    for col, cond in where.items():
        if col not in df.columns:
            raise KeyError(col)
        if isinstance(cond, dict):
            if len(cond) != 1:
                raise ValueError(
                    f"filter on '{col}' must use exactly one operator "
                    f"(got {', '.join(cond) or 'none'})"
                )
            ((op, val),) = cond.items()
            if op not in _FILTER_OPS:
                raise ValueError(
                    f"unknown filter operator '{op}' on '{col}' "
                    f"(expected one of: {', '.join(sorted(_FILTER_OPS))})"
                )
            selected &= _apply_op(df[col], op, val)
        else:
            selected &= df[col] == cond
    return selected


_WHERE_DESCRIPTION = (
    "Filter selecting rows. Each entry maps a column to either a literal for "
    'equality (e.g. {"city": "Berlin"}) or a single-key operator object: '
    '{"gt"|"gte"|"lt"|"lte"|"ne": value}, {"in": [values]}, or '
    '{"contains": substring} — e.g. {"population": {"gt": 1000000}}.'
)


# ── type checking ─────────────────────────────────────────────────────────────
#
# Cheap defence against silently corrupting a column's dtype: refuse writes
# whose values plainly don't fit the existing column (e.g. a string into a
# numeric column), with a message that names the column, its dtype, and the
# offending value — rather than letting pandas coerce or raise deep inside.


def _type_mismatch(dtype: Any, value: Any) -> str | None:
    if value is None:
        return None
    if pd.api.types.is_bool_dtype(dtype):
        if not isinstance(value, bool):
            return f"expected a boolean, got {type(value).__name__} ({value!r})"
    elif pd.api.types.is_numeric_dtype(dtype):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"expected a number, got {type(value).__name__} ({value!r})"
    return None


def _check_row_types(df: pd.DataFrame, row: dict[str, Any]) -> list[str]:
    issues = []
    for col, val in row.items():
        if col in df.columns:
            mismatch = _type_mismatch(df[col].dtype, val)
            if mismatch:
                issues.append(f"'{col}' ({df[col].dtype}): {mismatch}")
    return issues


# ── formatting helpers ────────────────────────────────────────────────────────


def _format_df(df: pd.DataFrame) -> str:
    total = len(df)
    body = str(df.head(_MAX_DISPLAY_ROWS).to_string(index=False))
    if total > _MAX_DISPLAY_ROWS:
        hidden = total - _MAX_DISPLAY_ROWS
        body += f"\n... ({hidden} more row(s) hidden — use 'where' or 'limit' to narrow)"
    return body


def _resolve(table_name: str | None, tables: dict[str, TableStore]) -> TableStore | None:
    if not tables:
        return None
    if table_name:
        return tables.get(table_name)
    return next(iter(tables.values()))


def _actor(ctx: dict[str, Any]) -> str:
    return str(ctx.get("agent_id") or "agent")


# ── shared dispatch wrapper: maps internal exceptions to clean messages ──────
#
# `_mask`/`_check_row_cap` raise KeyError/ValueError deliberately — those carry
# useful, agent-facing detail. Anything else is an internal error: the raw
# exception text (which can include pandas/library internals) must never reach
# the LLM, so it's swapped for a generic, safe message.


async def _safe(fn: Callable[[], Awaitable[str]]) -> str:
    try:
        return await fn()
    except KeyError as exc:
        return f"Unknown column: {exc}"
    except ValueError as exc:
        return f"Invalid request: {exc}"
    except Exception:
        return "Table operation failed due to an internal error."


# ── table_query ───────────────────────────────────────────────────────────────


class TableQueryInput(BaseModel):
    action: Literal["list", "load", "describe", "read", "export", "history"] = Field(
        description=(
            "'list' shows attached files and currently-loaded tables. "
            "'load' parses tabular data into the workspace (provide 'file_name' or "
            "'csv_text'). 'describe' summarises columns, dtypes, row count and "
            "version. 'read' returns rows (optionally filtered by 'where', narrowed "
            "to 'columns', capped by 'limit'). 'export' returns the whole table as "
            "CSV text. 'history' lists recent changes — check this in a multi-agent "
            "run to see whether another agent modified the table since you last "
            "looked, before relying on what you remember."
        )
    )
    table_name: str | None = Field(
        default=None,
        description=(
            "For 'load': key to store the table under (defaults to the file name). "
            "For other actions: which loaded table to operate on (defaults to the "
            "only loaded table, or the first one when multiple are loaded)."
        ),
    )
    file_name: str | None = Field(
        default=None,
        description="For action='load': the exact name of an attached file holding CSV data.",
    )
    csv_text: str | None = Field(
        default=None,
        description="For action='load': inline CSV text, used when no 'file_name' is given.",
    )
    columns: list[str] | None = Field(
        default=None,
        description="For action='read': restrict the output to these column names.",
    )
    limit: int | None = Field(
        default=None,
        description="For action='read': maximum number of rows to return.",
    )
    where: dict[str, Any] | None = Field(
        default=None,
        description=f"For action='read', optional. {_WHERE_DESCRIPTION}",
    )


class TableQueryTool(Tool):
    name = "table_query"
    description = (
        "Inspect a data table held in memory — read-only, never mutates anything. "
        "Use action='list' to see attached files and loaded tables, 'load' to parse "
        "one into the workspace, 'describe'/'read' to inspect columns and rows "
        '(supports filters like {"population": {"gt": 1000000}}), \'history\' to '
        "audit recent changes (important when other agents share this table), and "
        "'export' to retrieve it as CSV text. To create a table or change rows/"
        "columns, use the 'table_mutate' tool instead."
    )
    input_model = TableQueryInput

    async def execute(
        self, validated_input: BaseModel, context: dict[str, Any] | None = None
    ) -> str:
        if not isinstance(validated_input, TableQueryInput):
            return "Invalid input."
        inp = validated_input
        ctx = context or {}
        tables: dict[str, TableStore] | None = ctx.get("tables")
        if tables is None:
            return "Table workspace not available."

        async def run() -> str:
            if inp.action == "list":
                return _list(tables, ctx)
            if inp.action == "load":
                return await _load(inp, tables, ctx, _actor(ctx))

            store = _resolve(inp.table_name, tables)
            if store is None or store.df is None:
                return (
                    "No table loaded. Use action='load' (or the 'table_mutate' tool's "
                    "action='create') first."
                )
            if inp.action == "describe":
                return _describe(store)
            if inp.action == "read":
                return _read(inp, store.df)
            if inp.action == "export":
                return store.to_csv()
            if inp.action == "history":
                return _history(store)
            return f"Unknown action: {inp.action}"

        return await _safe(run)


def _list(tables: dict[str, TableStore], ctx: dict[str, Any]) -> str:
    files: dict[str, str] = ctx.get("files") or {}
    lines: list[str] = []
    if files:
        lines.append("Files you can load as a table (use action='load' with file_name):")
        lines.extend(f"  - {name}" for name in files)
    else:
        lines.append("No files are attached to this agent.")
    if tables:
        lines.append("\nLoaded tables:")
        for name, store in tables.items():
            if store.df is not None:
                r, c = store.df.shape
                lines.append(f"  - {name}: {r} row(s) x {c} column(s) (version {store.version})")
    return "\n".join(lines)


async def _load(
    inp: TableQueryInput, tables: dict[str, TableStore], ctx: dict[str, Any], actor: str
) -> str:
    if inp.csv_text:
        text = inp.csv_text
        key = inp.table_name or "csv"
    elif inp.file_name:
        files: dict[str, str] = ctx.get("files") or {}
        if inp.file_name not in files:
            available = ", ".join(files) if files else "none"
            return f"File '{inp.file_name}' not found. Available: {available}"
        text = files[inp.file_name]
        key = inp.table_name or inp.file_name
    else:
        return "action='load' requires 'file_name' or 'csv_text'."

    store = tables.get(key) or TableStore()
    tables[key] = store
    async with store.lock:
        store.load_csv(text)
        df = _loaded_df(store)
        store.record(actor, f"loaded {len(df)} row(s) x {df.shape[1]} column(s)")
        rows, cols, version = len(df), df.shape[1], store.version
        columns = ", ".join(map(str, df.columns))
    return (
        f"Loaded '{key}': {rows} row(s) x {cols} column(s) (version {version}).\nColumns: {columns}"
    )


def _describe(store: TableStore) -> str:
    df = _loaded_df(store)
    cols = ", ".join(f"{name} ({dtype})" for name, dtype in df.dtypes.items())
    sample = _format_df(df.head(_SAMPLE_ROWS))
    return (
        f"Table: {len(df)} row(s) x {df.shape[1]} column(s) — version {store.version}\n"
        f"Columns: {cols}\n\n"
        f"Sample (first {min(_SAMPLE_ROWS, len(df))} row(s)):\n{sample}"
    )


def _read(inp: TableQueryInput, df: pd.DataFrame) -> str:
    if inp.where:
        df = df[_mask(df, inp.where)]
    if inp.columns:
        missing = [c for c in inp.columns if c not in df.columns]
        if missing:
            return f"Unknown column(s): {', '.join(missing)}"
        df = df[inp.columns]
    if inp.limit is not None and inp.limit >= 0:
        df = df.head(inp.limit)
    if df.empty:
        return "No rows match."
    return _format_df(df)


def _history(store: TableStore) -> str:
    if not store.history:
        return f"No changes recorded yet (version {store.version})."
    return f"Current version: {store.version}\n" + "\n".join(store.history[-_MAX_HISTORY_ENTRIES:])


# ── table_mutate ──────────────────────────────────────────────────────────────


class TableMutateInput(BaseModel):
    action: Literal["create", "insert", "update", "delete", "add_column"] = Field(
        description=(
            "'create' builds a NEW table from scratch with the given 'columns' "
            "(optionally seeded with 'values'/'rows'). 'insert' appends row(s) from "
            "'values' and/or 'rows'. 'update' sets 'values' on rows matching 'where'. "
            "'delete' drops rows matching 'where'. 'add_column' adds a new column "
            "(e.g. a prediction column) from 'column_values' or a constant 'default'."
        )
    )
    table_name: str | None = Field(
        default=None,
        description=(
            "For 'create': name of the new table (defaults to 'table'). "
            "For other actions: which loaded table to operate on (defaults to the "
            "only loaded table, or the first one when multiple are loaded)."
        ),
    )
    columns: list[str] | None = Field(
        default=None,
        description="For action='create': the column names of the new table.",
    )
    where: dict[str, Any] | None = Field(
        default=None,
        description=f"Required for 'update' and 'delete'. {_WHERE_DESCRIPTION}",
    )
    values: dict[str, Any] | None = Field(
        default=None,
        description=(
            "For 'insert'/'create': a single row as {column: value}. "
            "For 'update': the columns to set on matched rows."
        ),
    )
    rows: list[dict[str, Any]] | None = Field(
        default=None,
        description="For 'insert'/'create': multiple rows, each a {column: value} object.",
    )
    column: str | None = Field(
        default=None, description="For action='add_column': the name of the new column."
    )
    column_values: list[Any] | None = Field(
        default=None,
        description=(
            "For action='add_column': one value per existing row (length must equal "
            "the current row count). This is how a prediction column is attached."
        ),
    )
    default: Any | None = Field(
        default=None,
        description="For action='add_column': a constant value to fill the new column.",
    )


class TableMutateTool(Tool):
    name = "table_mutate"
    description = (
        "Create or modify a data table held in memory. Use action='create' to build "
        "a new table from scratch, 'insert'/'update'/'delete' to change rows, and "
        "'add_column' to attach a column (e.g. a prediction column). Writes are "
        "type-checked against the existing schema and refused on mismatch, "
        "versioned, and immediately visible to other agents sharing this table — "
        "they can audit what changed via 'table_query' action='history'. To inspect "
        "a table without changing it, use the 'table_query' tool."
    )
    input_model = TableMutateInput

    async def execute(
        self, validated_input: BaseModel, context: dict[str, Any] | None = None
    ) -> str:
        if not isinstance(validated_input, TableMutateInput):
            return "Invalid input."
        inp = validated_input
        ctx = context or {}
        tables: dict[str, TableStore] | None = ctx.get("tables")
        if tables is None:
            return "Table workspace not available."
        actor = _actor(ctx)

        async def run() -> str:
            if inp.action == "create":
                return await _create(inp, tables, actor)

            store = _resolve(inp.table_name, tables)
            if store is None or store.df is None:
                return (
                    "No table loaded. Use the 'table_query' tool's action='load', "
                    "or action='create' here, first."
                )
            if inp.action == "insert":
                return await _insert(inp, store, actor)
            if inp.action == "update":
                return await _update(inp, store, actor)
            if inp.action == "delete":
                return await _delete(inp, store, actor)
            if inp.action == "add_column":
                return await _add_column(inp, store, actor)
            return f"Unknown action: {inp.action}"

        return await _safe(run)


async def _create(inp: TableMutateInput, tables: dict[str, TableStore], actor: str) -> str:
    if not inp.columns:
        return "action='create' requires 'columns' (the new table's column names)."
    name = inp.table_name or "table"
    seed: list[dict[str, Any]] = []
    if inp.values:
        seed.append(inp.values)
    if inp.rows:
        seed.extend(inp.rows)
    df = (
        pd.DataFrame(seed).reindex(columns=inp.columns)
        if seed
        else pd.DataFrame(columns=inp.columns)
    )
    _check_row_cap(len(df))

    store = tables.get(name) or TableStore()
    tables[name] = store
    async with store.lock:
        store.df = df
        store.record(actor, f"created with columns [{', '.join(inp.columns)}] ({len(df)} row(s))")
        version = store.version
    return (
        f"Created table '{name}' with columns: {', '.join(inp.columns)} "
        f"({len(df)} row(s), version {version})."
    )


async def _insert(inp: TableMutateInput, store: TableStore, actor: str) -> str:
    new_rows: list[dict[str, Any]] = []
    if inp.values:
        new_rows.append(inp.values)
    if inp.rows:
        new_rows.extend(inp.rows)
    if not new_rows:
        return "action='insert' requires 'values' or 'rows'."

    async with store.lock:
        df = _loaded_df(store)
        issues = [
            f"row {i}: {issue}"
            for i, row in enumerate(new_rows)
            for issue in _check_row_types(df, row)
        ]
        if issues:
            return "Type mismatch — refusing to insert:\n" + "\n".join(issues)
        _check_row_cap(len(df) + len(new_rows))
        store.df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
        store.record(actor, f"inserted {len(new_rows)} row(s)")
        total, version = len(store.df), store.version
    return f"Inserted {len(new_rows)} row(s). Table now has {total} row(s) (version {version})."


async def _update(inp: TableMutateInput, store: TableStore, actor: str) -> str:
    if not inp.where:
        return "action='update' requires 'where' to select rows."
    if not inp.values:
        return "action='update' requires 'values' (columns to set)."

    async with store.lock:
        df = _loaded_df(store)
        unknown = [c for c in inp.values if c not in df.columns]
        if unknown:
            return f"Unknown column(s): {', '.join(unknown)}"
        issues = _check_row_types(df, inp.values)
        if issues:
            return "Type mismatch — refusing to update:\n" + "\n".join(issues)
        selected = _mask(df, inp.where)
        for col, val in inp.values.items():
            df.loc[selected, col] = val
        n = int(selected.sum())
        store.record(actor, f"updated {n} row(s) matching {inp.where}")
        version = store.version
    return f"Updated {n} row(s) (version {version})."


async def _delete(inp: TableMutateInput, store: TableStore, actor: str) -> str:
    if not inp.where:
        return "action='delete' requires 'where' (refusing to delete the entire table)."

    async with store.lock:
        df = _loaded_df(store)
        selected = _mask(df, inp.where)
        removed = int(selected.sum())
        store.df = df[~selected].reset_index(drop=True)
        store.record(actor, f"deleted {removed} row(s) matching {inp.where}")
        remaining, version = len(store.df), store.version
    return f"Deleted {removed} row(s). {remaining} row(s) remain (version {version})."


async def _add_column(inp: TableMutateInput, store: TableStore, actor: str) -> str:
    if not inp.column:
        return "action='add_column' requires 'column'."

    async with store.lock:
        df = _loaded_df(store)
        verb = "Replaced" if inp.column in df.columns else "Added"
        if inp.column_values is not None:
            if len(inp.column_values) != len(df):
                return (
                    f"'column_values' has {len(inp.column_values)} item(s) but the table "
                    f"has {len(df)} row(s); they must match."
                )
            df[inp.column] = inp.column_values
            summary = f"{verb.lower()} column '{inp.column}' from {len(inp.column_values)} value(s)"
        elif inp.default is not None:
            df[inp.column] = inp.default
            summary = f"{verb.lower()} column '{inp.column}' with default {inp.default!r}"
        else:
            df[inp.column] = pd.NA
            summary = f"{verb.lower()} empty column '{inp.column}'"
        store.record(actor, summary)
        cols, version = df.shape[1], store.version
    return f"{verb} column '{inp.column}'. Table now has {cols} column(s) (version {version})."
