# Benchmarks

This directory contains lightweight benchmark generators and evaluators for the
FastAPI backend.

## Majority-Vote Needle-in-a-Haystack

The benchmark generates one text chunk per agent. A strict majority of agents
receive a chunk containing the _correct_ needle (the answer to the question);
the remaining agents receive a plausible-but-wrong needle (a different name
inserted into the same sentence template). Each chunk is padded with unrelated
distractor sentences.

In plurality-voting consensus, the majority should out-vote the minority and
the simulation should converge on the correct answer — typically within two
rounds, since the leading vote at round 0 already matches the correct answer.

The current implementation uses an in-memory store, so benchmark records are
lost when the server restarts.

## Create a Benchmark

Endpoint:

```text
POST /benchmark/needlehaystack/create
```

Request body:

```json
{
  "num_agents": 4,
  "sentences_per_agent": 6,
  "include_answer": false
}
```

Fields:

- `num_agents`: number of agent chunks to generate, between 2 and 50.
- `sentences_per_agent`: distractor sentences per agent chunk, between 5 and 50.
- `include_answer`: when `true`, the response includes the correct answer and
  the synthetic agent keys that hold it.

Example:

```bash
curl -X POST http://localhost:8000/benchmark/needlehaystack/create \
  -H "Content-Type: application/json" \
  -d '{"num_agents":3,"sentences_per_agent":6,"include_answer":true}'
```

Example response (3 agents, majority size = 2):

```json
{
  "benchmark_id": "f4bc8d9a-7f54-4e10-a8d7-32c2de622d4a",
  "question": "Which person in Organisation Delta has the blue security token?",
  "chunks": {
    "agent_1": "The person in Organisation Delta who has the blue security token is Priya Shah. ...",
    "agent_2": "The person in Organisation Delta who has the blue security token is Jonas Berg. ...",
    "agent_3": "The person in Organisation Delta who has the blue security token is Priya Shah. ..."
  },
  "answer": "Priya Shah",
  "correct_agents": ["agent_1", "agent_3"],
  "correct_agent_count": 2
}
```

When `include_answer` is `false`, `answer` and `correct_agents` are returned as
`null`.

## Evaluate an Answer

Endpoint:

```text
POST /benchmark/needlehaystack/evaluate
```

Request body:

```json
{
  "benchmark_id": "f4bc8d9a-7f54-4e10-a8d7-32c2de622d4a",
  "generated_answer": "Priya Shah"
}
```

Fields:

- `benchmark_id`: id returned by the create endpoint.
- `generated_answer`: answer produced by the consensus simulation.

The evaluator lowercases, trims whitespace, collapses repeated whitespace, and
removes punctuation before comparison. Because plurality voting strips
stop-words from each agent's vote, the comparator also accepts substring
matches in either direction (e.g. `"trump"` matches the canonical `"trump"`
without needing a literal full-string equality).

Example:

```bash
curl -X POST http://localhost:8000/benchmark/needlehaystack/evaluate \
  -H "Content-Type: application/json" \
  -d '{"benchmark_id":"f4bc8d9a-7f54-4e10-a8d7-32c2de622d4a","generated_answer":"PRIYA   SHAH!!!"}'
```

Example response:

```json
{
  "answer_correct": true,
  "correct_answer": "Priya Shah",
  "generated_answer": "PRIYA   SHAH!!!",
  "normalized_correct_answer": "priya shah",
  "normalized_generated_answer": "priya shah",
  "correct_agents": ["agent_1", "agent_3"]
}
```

Unknown benchmark ids return `404`.

## Driving the Benchmark

`api/benchmarks/run.py` drives the benchmark end-to-end against a running API.
It uses whichever agents are currently on the canvas, generates a benchmark
sized to that count, and evaluates the resulting plurality answer.

```bash
# Voting mode, 1 trial:
uv run --project api python -m api.benchmarks.run

# 5 trials with a tighter round budget:
uv run --project api python -m api.benchmarks.run --trials 5 --rounds 2
```

The runner only exercises plurality voting; the weighted consensus mode still
exists in `api/simulation/__init__.py` but is not part of this benchmark.
