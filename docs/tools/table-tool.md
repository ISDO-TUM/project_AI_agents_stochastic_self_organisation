# Table Tool

## What it is

The `table` tool gives an agent a structured, in-memory workspace for tabular data. An agent can load a CSV file, inspect and edit rows, attach a prediction column, and export the result. It is designed primarily for **tabular foundation models** (such as TabPFN) that take structured input and produce column-wise predictions, but it works with any LLM agent that needs to reason over tabular data.

---

## Why it matters

Most agent tools work with plain text. Real datasets are structured: rows, typed columns, and often missing values. Asking a model to work with raw CSV strings leads to problems like losing track of row indices, silent truncation, or producing malformed output.

The `table` tool solves this by owning the full table lifecycle:

- The model never parses raw CSV. It uses structured commands (`describe`, `read`, `add_column`) and gets structured replies. CSV is only the format at the boundary, on load and export.
- Row alignment is enforced. `add_column` requires the value list to match the exact row count, so prediction columns are never misaligned.
- Context is kept small. The `read` action supports filtering by row (`where`), selecting specific columns, and capping the result with `limit`, so the model only sees what it needs.
- Every action is recorded as a `tool` step in the activity log, making the sequence of mutations visible and reproducible.

---

## Shared workspace across agents

Each run maintains a single shared `tables` dictionary. The same dictionary is passed to every agent call in the run. This means:

- Agent A loads `passengers.csv` and adds a `survived` prediction column.
- Agent B, called later in the same run, can read or describe the table immediately without reloading the file. Agent A's changes are already there.

For single-agent runs the workspace is effectively private. For multi-agent pipelines it is the shared state that connects agents, enabling patterns like predict then review or predict then enrich.

---

## Actions

| Action       | Purpose                                                 | Key parameters                                          |
| ------------ | ------------------------------------------------------- | ------------------------------------------------------- |
| `list`       | Show attached files and currently loaded tables         |                                                         |
| `load`       | Load a CSV file or inline CSV text into the workspace   | `file_name`, `csv_text`, `table_name`                   |
| `create`     | Create a new empty table from scratch                   | `columns`, `table_name`, `rows` or `values` for seeding |
| `describe`   | Show column names, types, row count, and a sample       | `table_name`                                            |
| `read`       | Return rows, optionally filtered, projected, or limited | `where`, `columns`, `limit`, `table_name`               |
| `insert`     | Append one or more rows                                 | `values`, `rows`                                        |
| `update`     | Set column values on rows that match a filter           | `where`, `values`                                       |
| `delete`     | Remove rows that match a filter (a filter is required)  | `where`                                                 |
| `add_column` | Attach a new column from a list of values or a constant | `column`, `column_values`, `default`                    |
| `export`     | Return the current table as CSV text                    | `table_name`                                            |

### `add_column` - the prediction seam

This is the action a tabular foundation model uses to write its predictions back into the table. The `column_values` list must be exactly as long as the current row count. If it is not, the tool returns a clear error so the model can retry.

```
action='add_column', column='survived', column_values=[1, 0, 0, 1, 1, 0, 0, 1]
```

### `table_name` - multiple tables

When only one table is loaded, `table_name` can be left out and the tool resolves to it automatically. When multiple tables are loaded, pass `table_name` to pick the right one.

---

## How to use it

### Single agent: predict and export

1. Add a Dataset (CSV) source node to the canvas and connect it to the agent.
2. Give the agent the `table` tool.
3. Write a system prompt like:

   > Use the `table` tool: `action='list'` to find the dataset, `action='load'` it, inspect with `action='describe'`, predict the empty `survived` column for every row, write all predictions with `action='add_column'`, then `action='export'`.

The exported table appears as a result card in the activity log with a full-screen preview and a download button.

### Multi-agent pipeline: predict then review

Connect Agent A (predictor, with the `table` tool) and Agent B (reviewer, also with the `table` tool) to the same Dataset source. Agent A predicts and exports. Agent B can immediately call `describe` or `read` and will see Agent A's prediction column already in the table, because both share the same workspace.

### Fitting into consensus modes

The `table` tool works alongside the existing consensus modes without any special configuration:

- **Broadcast**: one tabular agent predicts and the result is exported.
- **Plurality voting or Weighted pooling**: agents emit a text summary of their prediction (e.g. "I predict 5 survivors") which is voted on like any other response. The table is their private working state.
- **Dynamic topology**: a tabular agent can discover and message a reviewer via the registry tool, passing the exported CSV for the reviewer to critique.

---

## Format support

CSV is the only supported format today. The format boundary is isolated inside `TableStore.load_csv`, so adding Excel or Parquet support would only change that one method without touching any of the CRUD logic.

---

## Demo

`demos/tabular-prediction.json` contains a single predictor agent wired to a Titanic sample dataset (8 rows, `survived` column empty). Import it, run with a prompt like "predict survival for every passenger", and the result table appears at the top of the activity log.

---

## SAP-RPT integration: the `table_predict` tool

The demo above lets the agent's own LLM fill the column. When you have access to the **SAP-RPT** tabular foundation model, the `table_predict` tool closes the loop with real, confidence-scored predictions — it is the read → predict → mutate bridge between this table workspace and SAP-RPT.

Give an agent `table_query` + `table_predict` (and optionally `table_mutate`), then:

1. `table_query` `action='load'` the attached dataset.
2. `table_predict` with `target_column` set to the column to fill. Rows where that column is **already filled** become SAP-RPT's in-context examples; rows where it is **blank** are predicted. The predictions are written back into the table (in place, or into `output_column` if you want to keep the original), versioned and audited exactly like a `table_mutate` write — so downstream agents see them immediately.
3. `table_query` `action='export'` to retrieve the completed CSV.

The response includes the SAP-RPT confidence per row plus a mean-confidence guidance line that an agent can use to calibrate its conviction during deliberation.

`table_predict` needs a SAP-RPT API key. Enter it in the UI's **API Keys** dialog (the **SAP-RPT** entry, sent as the `X-SAP-RPT-Key` header) or set `SAP_RPT_API_KEY` in `.env`; the base URL defaults to `https://rpt.cloud.sap` and can be overridden with `SAP_RPT_BASE_URL`. For ad-hoc rows that are not backed by a loaded table, `rpt_predict` (raw JSON rows) and `rpt_chat` (natural-language what-if questions) remain available.

`demos/predictive-maintenance.json` is a three-agent consensus example: a **Data Analyst** loads `equipment-maintenance.csv`, predicts the blank `rul_days` (remaining useful life) column with `table_predict`, and a **Strategic Analyst** and **Risk Assessor** read the shared table and deliberate over whether to take each machine offline.
