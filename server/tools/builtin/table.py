"""Tabular CRUD tool: parse a table and let the agent read/mutate it.

This is the data-handling half of tabular-foundation-model support. A user
uploads tabular data (a CSV today; Excel later) and the agent uses this tool to
load it into an in-memory workspace and perform CRUD operations on it. The
result — typically the original table with a *prediction column* appended — is
read back out with ``action='export'``.

The actual prediction is produced by a tabular foundation model (the TabPFN
family expects a pandas ``DataFrame`` / numpy matrix, never a raw file), which
is wired in separately. This tool only owns the table lifecycle and the
``add_column`` seam that the model writes its prediction through.

Lifecycle mirrors ``RegistryTool``: a single mutable :class:`TableStore` is
built per agent run, placed in the tool ``context``, and mutated in place across
calls. CSV parsing is the only format-specific boundary — swapping in an Excel
reader later touches nothing else.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, Field

from ..base import Tool

# Cap on rows echoed back to the LLM so a large table never floods the context.
_MAX_DISPLAY_ROWS = 50
# Rows shown in the `describe` preview.
_SAMPLE_ROWS = 5


@dataclass
class TableStore:
    """In-memory tabular workspace for a single agent run.

    Holds one pandas ``DataFrame``, mutated in place across CRUD tool calls. The
    CSV parser is the only format-specific boundary; an Excel reader would slot
    in alongside ``load_csv`` without touching any CRUD logic.
    """

    df: pd.DataFrame | None = None

    # ── ingestion (the only format-specific boundary) ──────────────────────────
    def load_csv(self, text: str) -> None:
        self.df = pd.read_csv(io.StringIO(text))

    def to_csv(self) -> str:
        return "" if self.df is None else str(self.df.to_csv(index=False))


def _mask(df: pd.DataFrame, where: dict[str, Any]) -> Any:
    """Boolean row mask for an equality filter ``{column: value}``."""
    selected = pd.Series(True, index=df.index)
    for col, val in where.items():
        if col not in df.columns:
            raise KeyError(col)
        selected &= df[col] == val
    return selected


def _format_df(df: pd.DataFrame) -> str:
    """Render a DataFrame for the LLM, truncating beyond ``_MAX_DISPLAY_ROWS``."""
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
            "'list' shows the attached files you can load as a table. "
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
        "action='export'. All changes persist within the current run."
    )
    input_model = TableInput

    async def execute(
        self, validated_input: BaseModel, context: dict[str, Any] | None = None
    ) -> str:
        if not isinstance(validated_input, TableInput):
            return "Invalid input."
        inp = validated_input
        ctx = context or {}
        store: TableStore | None = ctx.get("table")
        if store is None:
            return "Table workspace not available."

        try:
            return self._dispatch(inp, store, ctx)
        except Exception as exc:  # surface failures to the LLM instead of crashing the run
            return f"Table operation failed: {exc}"

    def _dispatch(self, inp: TableInput, store: TableStore, ctx: dict[str, Any]) -> str:
        if inp.action == "list":
            return self._list(ctx)
        if inp.action == "load":
            return self._load(inp, store, ctx)
        if inp.action == "create":
            return self._create(inp, store)

        df = store.df
        if df is None:
            return "No table loaded. Use action='load' first."

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

    # ── action handlers ─────────────────────────────────────────────────────────

    def _list(self, ctx: dict[str, Any]) -> str:
        files: dict[str, str] = ctx.get("files") or {}
        if not files:
            return "No files are attached to this agent."
        lines = "\n".join(f"- {name}" for name in files)
        return f"Files you can load as a table (use action='load' with file_name):\n{lines}"

    def _load(self, inp: TableInput, store: TableStore, ctx: dict[str, Any]) -> str:
        if inp.csv_text:
            text = inp.csv_text
        elif inp.file_name:
            files: dict[str, str] = ctx.get("files") or {}
            if inp.file_name not in files:
                available = ", ".join(files) if files else "none"
                return f"File '{inp.file_name}' not found. Available: {available}"
            text = files[inp.file_name]
        else:
            return "action='load' requires 'file_name' or 'csv_text'."

        store.load_csv(text)
        df = store.df
        if df is None:  # unreachable after a successful parse; keeps the type checker happy
            return "Failed to load table."
        rows, cols = df.shape
        return (
            f"Loaded table: {rows} row(s) x {cols} column(s).\n"
            f"Columns: {', '.join(map(str, df.columns))}"
        )

    def _create(self, inp: TableInput, store: TableStore) -> str:
        if not inp.columns:
            return "action='create' requires 'columns' (the new table's column names)."
        seed: list[dict[str, Any]] = []
        if inp.values:
            seed.append(inp.values)
        if inp.rows:
            seed.extend(inp.rows)
        # Seed rows are aligned to the declared columns: missing keys become NaN,
        # extra keys are dropped, so the table's schema is exactly `columns`.
        if seed:
            store.df = pd.DataFrame(seed).reindex(columns=inp.columns)
        else:
            store.df = pd.DataFrame(columns=inp.columns)
        return f"Created table with columns: {', '.join(inp.columns)} ({len(store.df)} row(s))."

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
