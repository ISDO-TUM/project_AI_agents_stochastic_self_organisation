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

### `supply-chain-disruption-swarm.json` (final-presentation showcase)

A supply-chain disruption war room at a fictional automotive tier-1
(Meridian Drive Systems). The primary supplier of a safety-critical
microcontroller declares force majeure; the swarm has to work out how to
keep the ECU lines running. Built for the SAP audience — every knowledge
file reads like an ERP extract (supplier master, QM qualification records,
controlling exposure model, freight quotes).

Six agents, each grounded in its own data:

- **Supply Chain Lead** — disruption alert, supplier master, and a _stale_
  2025 scorecard saying the alternate supplier failed its PPAP audit.
- **Logistics Planner** — freight quotes (air vs sea, bonded-warehouse release).
- **Production Planner** — consumption vs inventory → week-by-week coverage.
- **Finance Controller** — penalty/margin exposure model, approval threshold.
- **Quality & Supplier Compliance** — _current_ QM records showing the
  alternate supplier was re-qualified in 2026-03; corrects the stale scorecard.
- **Data Privacy Officer** — deliberately irrelevant; should abstain.

Suggested prompt:

> Taicang has stopped shipping MCU-748 for six weeks. What is the best
> mitigation plan to keep our ECU lines running, and what should we do first?

Why it demos self-organization over orchestration: no workflow was scripted
for this event, yet the specialists split the problem along their expertise,
build on each other via citations (coverage timeline → cost model), resolve
the stale-vs-current qualification conflict in quality's favor, and the
irrelevant agent stays out. The expected outcome is a combined plan —
airfreight the bonded stock as a bridge, ramp NovaChip Penang for the
remaining weeks — that no single agent's data was sufficient to produce.

### `order-allocation-swarm.json` (tabular-tools showcase · two prompts)

Sales-order allocation under a supply shortage at a fictional pump maker
(Falkenberg Pumpen GmbH). Only 5,000 units of material 4711 are available
in July against 8,000 units of open orders — the swarm has to decide who
gets cut and **write the allocation into a shared table**, not just talk
about it. Built for the SAP audience: the scenario is classic ATP/backorder
processing, and it shows agents with read/write access to tabular data
(`table_query` / `table_mutate`) alongside knowledge files.

The canvas carries a standby **expedite lever** (an extra casting batch at a
premium) and a credit block that treasury can partially lift, so the same
setup drives two runs of very different depth — see the two prompts below.

Six agents:

- **Order Fulfillment Manager** — loads `open_sales_orders.csv`, gathers
  the specialists' input, writes the final `allocated_qty` column (and an
  optional `expedite_qty` column when asked), exports the completed table.
- **Credit & Receivables Controller** — credit memo shows Helios (C-2002)
  under an active credit block; stamps a `credit_check` column
  (`OK`/`BLOCKED`) into the shared table. Honours a treasury partial-release
  when a run supplies one.
- **Key Account Manager** — frame-contract notes: Bergmann carries a 95%
  service-level clause (€60k penalty), Quantex is a strategic pilot
  account, Nordwind is a spot buyer.
- **Margin Analyst** — per-unit contribution margins; computes where the
  cut is cheapest and weighs the €4.00 expedite premium against margin/penalty.
- **Production & Expedite Planner** — owns the standby expedite lever: one
  batch of up to 800 units for 2026-07-28 at a €4.00/unit premium, reserved
  by policy for protecting must-serve or penalty orders.
- **Data Privacy Officer** — deliberately irrelevant; should abstain.

The scenario ships with **two prompts** — a simple one for a clean, easy-to-
follow live run, and a harder one that injects a live escalation to force a
re-optimisation and richer table writes.

#### Simple prompt

> We can only ship 5,000 units of material 4711 in July against 8,000 on
> order. Decide how to allocate the available stock across the open sales
> orders and write the allocation into the shared table.

Each order maps to one clear reason, so the answer is easy to follow live:

- **Bergmann → full 3,000** — frame contract, any short delivery triggers a
  penalty (must-serve).
- **Helios → 0** — active credit block (frees 2,500 units).
- **Quantex → full 1,000** — strategic pilot account.
- **Nordwind → 1,000 of 1,500** — spot buyer, lowest margin, no penalty, so
  the 500-unit shortfall lands here.

→ allocation **3,000 / 0 / 1,000 / 1,000** (sums to the 5,000 available). The
expedite batch stays on standby (no penalty is at stake), and the privacy
officer abstains. No single agent's data is sufficient: the credit block, the
penalty clause, and the margin ranking each come from a different specialist.

#### Complicated prompt (escalation)

> Same July shortage of material 4711 (5,000 available against 8,000 on
> order), but two updates just landed. Treasury confirms Helios (C-2002) will
> clear €120k of its overdue by 2026-07-15 — enough for a partial credit
> release of up to 1,500 units of its order. And plant management has
> pre-approved the standby expedite batch (up to 800 units, arriving
> 2026-07-28 at a €4.00/unit premium) if it prevents financial damage.
> Re-optimise the allocation to minimise total financial damage (contract
> penalties + lost margin − expedite value), decide whether and how much to
> expedite and how much of Helios to release, write the final allocation
> (and any expedite plan) into the shared table, and add a one-line
> contingency for whatever stays short if the 2026-08-03 batch slips.

This one has no single tidy answer — that is the point. The must-serve orders
still anchor it (Bergmann 3,000, Quantex 1,000), but freeing Helios flips the
residual decision: with the credit cap lifted, Helios (€9.20 margin) now
out-ranks Nordwind (€5.40) for the remaining base capacity, so the allocation
shifts toward **3,000 / Helios up to ~1,000 / Nordwind cut / 1,000** — the
mirror image of the simple run. The expedite batch becomes a genuine
judgement call (no order left carries a penalty, yet expedited Helios units
still clear their premium), which is exactly the kind of split that surfaces
a **contested synthesis** in the ratification step. Great for showing the
swarm reasoning under a moving target rather than reciting a fixed answer.

**Seeing the write.** The shared table is in-memory for the run. The Order
Fulfillment Manager's final message ends with a `FINAL ALLOCATION TABLE:`
block — the completed table as a Markdown table (the filled `allocated_qty`
column, plus `expedite_qty` on the complicated run) — followed by a
`WRITE CONFIRMATION: table version N, columns written: ...` line drawn from
`table_query` action='history'. That history shows different agents writing to
the same table: the credit controller's `credit_check` column and the
manager's `allocated_qty` (and `expedite_qty`). The Confirmed board lifts that
table out of the message and renders it as a **Result table** directly beneath
the synthesised final answer (and in the completion overlay), so you see the
allocation without scrolling the raw message.

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
