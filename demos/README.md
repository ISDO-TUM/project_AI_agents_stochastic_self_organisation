# Demo configurations

Importable canvas configurations for demos and the team. Each JSON file
captures a complete canvas: agents, knowledge files (with their content), and
the edges between them.

## Importing

1. Start the app (`pnpm dev`) and open the canvas.
2. Click **Import** on the toolbar and pick one of the JSON files in this
   directory.
3. The agents, files, and edges are pushed to the backend, so the simulation
   has the same state the JSON describes.

## Running

After import, type a prompt in the bottom bar and pick the **voting** consensus
mode. The plurality answer should converge within two rounds — the leading
vote at round 0 already matches the majority answer, and round 1 confirms it.

## Running the benchmark

The benchmark is **independent of the demo** — it provisions its own
temporary agents, runs the trials, and deletes them at the end. Whatever
demo you have imported on the canvas is left alone.

With the dev server running:

```bash
uv run --project api python -m api.benchmarks.run                # 1 trial, 3 agents
uv run --project api python -m api.benchmarks.run --trials 5     # 5 trials
uv run --project api python -m api.benchmarks.run --agents 5     # 5 benchmark agents
uv run --project api python -m api.benchmarks.run --trials 5 --log
uv run --project api python -m api.benchmarks.run --log results/run1.log
```

The `--log` flag mirrors stdout to a file. Pass it without a value to write
to `./benchmark-YYYYMMDD-HHMM.log`, or pass an explicit path to override.

For each trial the runner creates one knowledge file per agent (with the
chunk content), attaches it, runs the simulation in voting mode, then
deletes those files. After the last trial the temporary agents are deleted
too.

## Files

### `approved-supplier.json` (recommended walkthrough)

A procurement scenario demonstrating conflict resolution across agents:

- **Procurement Lead** has the current `2026_supplier_contract.txt` —
  master agreement names **Acme Computers** as the approved vendor.
- **Compliance Officer** has the matching `compliance_memo_2026.txt` —
  audit confirms **Acme Computers** is the only approved supplier.
- **Field Operations** has a stale `field_ops_legacy_note.txt` from 2024 —
  it still points at **BetaSystems**.

Suggested prompt:

> Who is the currently approved supplier for office laptops?

Two of the three agents read **Acme Computers** from their files; one reads
the outdated **BetaSystems**. Plurality voting picks `acme computers`,
demonstrating the core message: _the system tolerates one stakeholder being
out of date because the majority of grounded sources still agree_. This is
the same pattern encountered whenever procurement rules, compliance memos,
and on-site notes drift apart between systems.

### `president-majority.json`

Toy version of the same idea — keep around as a sanity check. Three agents,
each connected to its own copy of `Name of the president.txt`. Two say
`The president of America is Trump`; one says `The president of America is
Joe Biden`. Suggested prompt: _Who is the president of America?_ Plurality
picks `trump`.

Use either file as a template for new majority-vote demos: keep
`tools: ["files"]` on every agent, attach one file per agent (with the
content the agent should "know"), and keep the sentence framing across
files identical so votes collapse to the same normalised answer.
