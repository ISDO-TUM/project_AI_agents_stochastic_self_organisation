"""Tabular CRUD tool — lets an agent load, inspect, and mutate a CSV table.

The tool manages an in-memory workspace of named ``TableStore`` objects.  A
``TableStore`` is created on first ``load`` or ``create`` and keyed by the file
name (or an explicit ``table_name``).  Because the same ``tables`` dict is
shared across every agent call in a run, mutations made by one agent are
immediately visible to the next — a predictor can add a column and a reviewer
downstream can inspect it without re-loading the file.

CSV parsing is the only format-specific boundary; an Excel reader would slot in
alongside ``load_csv`` without touching any CRUD logic.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, Field

from ..base import Tool

_MAX_DISPLAY_ROWS = 50
_SAMPLE_ROWS = 5


@dataclass
class TableStore:
    """In-memory workspace for one table, shared across agent calls in a run."""

    df: pd.DataFrame | None = None

    def load_csv(self, text: str) -> None:
        self.df = pd.read_csv(io.StringIO(text))

    def to_csv(self) -> str:
        return "" if self.df is None else str(self.df.to_csv(index=False))


def _mask(df: pd.DataFrame, where: dict[str, Any]) -> Any:
    selected = pd.Series(True, index=df.index)
    for col, val in where.items():
        if col not in df.columns:
            raise KeyError(col)
        selected &= df[col] == val
    return selected


def _format_df(df: pd.DataFrame) -> str:
    total = len(df)
    body = str(df.head(_MAX_DISPLAY_ROWS).to_string(index=False))
    if total > _MAX_DISPLAY_ROWS:
        hidden = total - _MAX_DISPLAY_ROWS
        body += f"\n... ({hidden} more row(s) hidden — use 'where' or 'limit' to narrow)"
    return body


class TableInput(BaseModel):
    action: Literal[
        "list",
        "load",
        "create",
        "describe",
        "read",
        "insert",
        "update",
        "delete",
        "add_column",
        "export",
    ] = Field(
        description=(
            "'list' shows attached files and currently-loaded tables. "
            "'load' parses tabular data into the workspace (provide 'file_name' or "
            "'csv_text'). 'create' builds a NEW table from scratch with the given "
            "'columns' (optionally seeded with 'values'/'rows'). "
            "'describe' summarises columns, dtypes and row count. "
            "'read' returns rows (optionally filtered by 'where', narrowed to "
            "'columns', capped by 'limit'). 'insert' appends row(s) from 'values' "
            "and/or 'rows'. 'update' sets 'values' on rows matching 'where'. "
            "'delete' drops rows matching 'where'. 'add_column' adds a new column "
            "(e.g. a prediction column) from 'column_values' or a constant "
            "'default'. 'export' returns the whole table as CSV text."
        )
    )
    table_name: str | None = Field(
        default=None,
        description=(
            "For 'load': key to store the table under (defaults to the file name). "
            "For 'create': name of the new table (defaults to 'table'). "
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
        description=(
            "For action='read': restrict the output to these column names. "
            "For action='create': the column names of the new table."
        ),
    )
    limit: int | None = Field(
        default=None,
        description="For action='read': maximum number of rows to return.",
    )
    where: dict[str, Any] | None = Field(
        default=None,
        description=(
            'Equality filter selecting rows, e.g. {"city": "Berlin"}. '
            "Required for 'update' and 'delete'; optional for 'read'."
        ),
    )
    values: dict[str, Any] | None = Field(
        default=None,
        description=(
            "For 'insert': a single row as {column: value}. "
            "For 'update': the columns to set on matched rows."
        ),
    )
    rows: list[dict[str, Any]] | None = Field(
        default=None,
        description="For 'insert': multiple rows, each a {column: value} object.",
    )
    column: str | None = Field(
        default=None,
        description="For action='add_column': the name of the new column.",
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


class TableTool(Tool):
    name = "table"
    description = (
        "Work with a data table held in memory. Use action='list' to see which "
        "files are attached and action='load' to parse one into the workspace, or "
        "action='create' to build a new table from scratch for the task. Then use "
        "'describe'/'read' to inspect it and "
        "'insert'/'update'/'delete'/'add_column' to modify it. A prediction column "
        "is attached with action='add_column'. Retrieve the final table as CSV with "
        "action='export'. All changes persist within the current run and are visible "
        "to other agents in the same pipeline."
    )
    input_model = TableInput

    async def execute(
        self, validated_input: BaseModel, context: dict[str, Any] | None = None
    ) -> str:
        if not isinstance(validated_input, TableInput):
            return "Invalid input."
        inp = validated_input
        ctx = context or {}
        tables: dict[str, TableStore] | None = ctx.get("tables")
        if tables is None:
            return "Table workspace not available."

        try:
            return self._dispatch(inp, tables, ctx)
        except Exception as exc:
            return f"Table operation failed: {exc}"

    def _dispatch(self, inp: TableInput, tables: dict[str, TableStore], ctx: dict[str, Any]) -> str:
        if inp.action == "list":
            return self._list(tables, ctx)
        if inp.action == "load":
            return self._load(inp, tables, ctx)
        if inp.action == "create":
            return self._create(inp, tables)

        store = self._resolve(inp.table_name, tables)
        if store is None:
            return "No table loaded. Use action='load' or action='create' first."
        df = store.df
        if df is None:
            return "No table loaded."

        if inp.action == "describe":
            return self._describe(df)
        if inp.action == "read":
            return self._read(inp, df)
        if inp.action == "insert":
            return self._insert(inp, store, df)
        if inp.action == "update":
            return self._update(inp, df)
        if inp.action == "delete":
            return self._delete(inp, store, df)
        if inp.action == "add_column":
            return self._add_column(inp, df)
        if inp.action == "export":
            return store.to_csv()
        return f"Unknown action: {inp.action}"

    # ── helpers ─────────────────────────────────────────────────────────────────

    def _resolve(self, table_name: str | None, tables: dict[str, TableStore]) -> TableStore | None:
        if not tables:
            return None
        if table_name:
            return tables.get(table_name)
        return next(iter(tables.values()))

    # ── action handlers ─────────────────────────────────────────────────────────

    def _list(self, tables: dict[str, TableStore], ctx: dict[str, Any]) -> str:
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
                    lines.append(f"  - {name}: {r} row(s) x {c} column(s)")
        return "\n".join(lines)

    def _load(self, inp: TableInput, tables: dict[str, TableStore], ctx: dict[str, Any]) -> str:
        if inp.csv_text:
            text = inp.csv_text
            key = inp.table_name or inp.file_name or "csv"
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
        store.load_csv(text)
        tables[key] = store
        df = store.df
        if df is None:
            return "Failed to load table."
        rows, cols = df.shape
        return (
            f"Loaded '{key}': {rows} row(s) x {cols} column(s).\n"
            f"Columns: {', '.join(map(str, df.columns))}"
        )

    def _create(self, inp: TableInput, tables: dict[str, TableStore]) -> str:
        if not inp.columns:
            return "action='create' requires 'columns' (the new table's column names)."
        name = inp.table_name or "table"
        seed: list[dict[str, Any]] = []
        if inp.values:
            seed.append(inp.values)
        if inp.rows:
            seed.extend(inp.rows)
        store = TableStore()
        if seed:
            store.df = pd.DataFrame(seed).reindex(columns=inp.columns)
        else:
            store.df = pd.DataFrame(columns=inp.columns)
        tables[name] = store
        return (
            f"Created table '{name}' with columns: {', '.join(inp.columns)} "
            f"({len(store.df)} row(s))."
        )

    def _describe(self, df: pd.DataFrame) -> str:
        cols = ", ".join(f"{name} ({dtype})" for name, dtype in df.dtypes.items())
        sample = _format_df(df.head(_SAMPLE_ROWS))
        return (
            f"Table: {len(df)} row(s) x {df.shape[1]} column(s)\n"
            f"Columns: {cols}\n\n"
            f"Sample (first {min(_SAMPLE_ROWS, len(df))} row(s)):\n{sample}"
        )

    def _read(self, inp: TableInput, df: pd.DataFrame) -> str:
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

    def _insert(self, inp: TableInput, store: TableStore, df: pd.DataFrame) -> str:
        new_rows: list[dict[str, Any]] = []
        if inp.values:
            new_rows.append(inp.values)
        if inp.rows:
            new_rows.extend(inp.rows)
        if not new_rows:
            return "action='insert' requires 'values' or 'rows'."
        store.df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
        return f"Inserted {len(new_rows)} row(s). Table now has {len(store.df)} row(s)."

    def _update(self, inp: TableInput, df: pd.DataFrame) -> str:
        if not inp.where:
            return "action='update' requires 'where' to select rows."
        if not inp.values:
            return "action='update' requires 'values' (columns to set)."
        unknown = [c for c in inp.values if c not in df.columns]
        if unknown:
            return f"Unknown column(s): {', '.join(unknown)}"
        selected = _mask(df, inp.where)
        for col, val in inp.values.items():
            df.loc[selected, col] = val
        return f"Updated {int(selected.sum())} row(s)."

    def _delete(self, inp: TableInput, store: TableStore, df: pd.DataFrame) -> str:
        if not inp.where:
            return "action='delete' requires 'where' (refusing to delete the entire table)."
        selected = _mask(df, inp.where)
        removed = int(selected.sum())
        store.df = df[~selected].reset_index(drop=True)
        return f"Deleted {removed} row(s). {len(store.df)} row(s) remain."

    def _add_column(self, inp: TableInput, df: pd.DataFrame) -> str:
        if not inp.column:
            return "action='add_column' requires 'column'."
        verb = "Replaced" if inp.column in df.columns else "Added"
        if inp.column_values is not None:
            if len(inp.column_values) != len(df):
                return (
                    f"'column_values' has {len(inp.column_values)} item(s) but the table "
                    f"has {len(df)} row(s); they must match."
                )
            df[inp.column] = inp.column_values
        elif inp.default is not None:
            df[inp.column] = inp.default
        else:
            df[inp.column] = pd.NA
        return f"{verb} column '{inp.column}'. Table now has {df.shape[1]} column(s)."
