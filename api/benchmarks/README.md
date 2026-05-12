# Benchmarks

This directory contains lightweight benchmark generators and evaluators for the
FastAPI backend.

## Needle-in-a-Haystack

The Needle-in-a-Haystack benchmark creates one text chunk per agent. One randomly
selected chunk contains a hidden fact, called the needle. The benchmark returns a
question that can only be answered by finding that needle.

The current implementation uses an in-memory store, so benchmark records are lost
when the server restarts. For production usage, replace the store with Redis,
Postgres, or SQLite.

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
  the agent containing the needle.

Example:

```bash
curl -X POST http://localhost:8000/benchmark/needlehaystack/create \
  -H "Content-Type: application/json" \
  -d '{"num_agents":4,"sentences_per_agent":6,"include_answer":true}'
```

Example response:

```json
{
  "benchmark_id": "f4bc8d9a-7f54-4e10-a8d7-32c2de622d4a",
  "question": "Which person in Organisation Delta has the blue security token?",
  "chunks": {
    "agent_1": "Mira Novak works in Organisation Atlas and is responsible for data governance. ...",
    "agent_2": "In Organisation Delta, Clara Jensen manages archive access. ...",
    "agent_3": "The person in Organisation Delta who has the blue security token is Priya Shah. ...",
    "agent_4": "Organisation Cygnus lists Jonas Berg as the contact for internal reporting. ..."
  },
  "answer": "Priya Shah",
  "needle_agent": "agent_3"
}
```

When `include_answer` is `false`, `answer` and `needle_agent` are returned as
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
  "generated_answer": "Priya Shah",
  "selected_agent": "agent_3"
}
```

Fields:

- `benchmark_id`: id returned by the create endpoint.
- `generated_answer`: answer produced by an agent or workflow.
- `selected_agent`: optional agent id routed to or selected by the workflow.

The evaluator uses normalized exact match for answers. It lowercases, trims
whitespace, collapses repeated whitespace, and removes punctuation before
comparison.

Example:

```bash
curl -X POST http://localhost:8000/benchmark/needlehaystack/evaluate \
  -H "Content-Type: application/json" \
  -d '{"benchmark_id":"f4bc8d9a-7f54-4e10-a8d7-32c2de622d4a","generated_answer":"PRIYA   SHAH!!!","selected_agent":"agent_3"}'
```

Example response:

```json
{
  "answer_correct": true,
  "routing_correct": true,
  "correct_answer": "Priya Shah",
  "generated_answer": "PRIYA   SHAH!!!",
  "normalized_correct_answer": "priya shah",
  "normalized_generated_answer": "priya shah",
  "needle_agent": "agent_3",
  "selected_agent": "agent_3"
}
```

If `selected_agent` is omitted, `routing_correct` is `null`. Unknown benchmark
ids return `404`.
