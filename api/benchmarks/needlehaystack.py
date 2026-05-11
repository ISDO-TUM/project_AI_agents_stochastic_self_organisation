"""Needle-in-a-haystack benchmark routes."""

from __future__ import annotations

import secrets
import string
import uuid
from dataclasses import dataclass

from fastapi import APIRouter, HTTPException, status

from api.schemas import (
    BenchmarkRecord,
    CanvasPosition,
    CreateBenchmarkRequest,
    CreateBenchmarkResponse,
    CreateDemoBenchmarkRequest,
    CreateDemoBenchmarkResponse,
    DemoBenchmarkRecord,
    DemoCanvas,
    DemoCanvasAgent,
    DemoCanvasEdge,
    DemoCanvasSource,
    DemoNeedleRecord,
    EvaluateBenchmarkRequest,
    EvaluateBenchmarkResponse,
    GetDemoBenchmarkNeedlesResponse,
)

router = APIRouter(prefix="/benchmark/needlehaystack", tags=["Benchmarks"])

BENCHMARKS: dict[str, BenchmarkRecord] = {}
DEMO_BENCHMARKS: dict[str, DemoBenchmarkRecord] = {}

_DEMO_AGENT_COUNT = 3
_DEMO_SYSTEM_PROMPT = (
    "You answer questions about approved suppliers using your attached files. "
    "If the answer is in your files, reply with just the supplier company name "
    "(no full sentence, no explanation). If it is not, reply with the literal string "
    '"unknown".'
)
_DEMO_AGENT_TEMPLATES = [
    {
        "id": "a1111111-1111-4111-8111-111111111111",
        "name": "Procurement Lead",
        "description": "Owns supplier contracts and the approved-vendor list.",
        "connections": [
            "a2222222-2222-4222-8222-222222222222",
            "a3333333-3333-4333-8333-333333333333",
        ],
        "position": CanvasPosition(x=200, y=160),
    },
    {
        "id": "a2222222-2222-4222-8222-222222222222",
        "name": "Compliance Officer",
        "description": "Verifies suppliers meet current compliance and audit requirements.",
        "connections": ["a3333333-3333-4333-8333-333333333333"],
        "position": CanvasPosition(x=460, y=80),
    },
    {
        "id": "a3333333-3333-4333-8333-333333333333",
        "name": "Field Operations",
        "description": "On-site team using whichever supplier note they had on hand.",
        "connections": [],
        "position": CanvasPosition(x=760, y=160),
    },
]
_DEMO_SOURCE_TEMPLATES = [
    {
        "id": "f1111111-1111-4111-8111-111111111111",
        "name": "2026_supplier_contract.txt",
        "position": CanvasPosition(x=200, y=460),
    },
    {
        "id": "f2222222-2222-4222-8222-222222222222",
        "name": "compliance_memo_2026.txt",
        "position": CanvasPosition(x=460, y=380),
    },
    {
        "id": "f3333333-3333-4333-8333-333333333333",
        "name": "field_ops_legacy_note.txt",
        "position": CanvasPosition(x=760, y=460),
    },
]
_DEMO_EDGE_TEMPLATES = [
    (
        "e-pl-cf",
        "a1111111-1111-4111-8111-111111111111",
        "a2222222-2222-4222-8222-222222222222",
    ),
    (
        "e-pl-fo",
        "a1111111-1111-4111-8111-111111111111",
        "a3333333-3333-4333-8333-333333333333",
    ),
    (
        "e-cf-fo",
        "a2222222-2222-4222-8222-222222222222",
        "a3333333-3333-4333-8333-333333333333",
    ),
    (
        "e-pl-f1",
        "a1111111-1111-4111-8111-111111111111",
        "f1111111-1111-4111-8111-111111111111",
    ),
    (
        "e-cf-f2",
        "a2222222-2222-4222-8222-222222222222",
        "f2222222-2222-4222-8222-222222222222",
    ),
    (
        "e-fo-f3",
        "a3333333-3333-4333-8333-333333333333",
        "f3333333-3333-4333-8333-333333333333",
    ),
]

PEOPLE = [
    "Mira Novak",
    "Alice Moreno",
    "Jonas Berg",
    "Priya Shah",
    "Elena Rossi",
    "Clara Jensen",
    "Martin Weber",
    "Noah Klein",
    "Fatima Rahman",
    "Daniel Cho",
    "Sofia Lind",
    "Lukas Meyer",
]

ORGANISATIONS = [
    "Organisation Atlas",
    "Organisation Borealis",
    "Organisation Cygnus",
    "Organisation Delta",
    "Organisation Meridian",
]

ROLES = [
    "supplier onboarding",
    "quarterly audit reviews",
    "data governance",
    "procurement records",
    "internal reporting",
    "archive access",
    "infrastructure planning",
    "regional coordination",
]

ATTRIBUTES = [
    "clearance level Y",
    "the blue security token",
    "project access code Z",
    "the emergency override badge",
    "the confidential archive key",
]

DISTRACTOR_TEMPLATES = [
    "{person} works in {org} and is responsible for {role}.",
    "In {org}, {person} manages {role}.",
    "{org} lists {person} as the contact for {role}.",
    "{person} supports {role} within {org}.",
]


@dataclass(frozen=True)
class _NeedleFact:
    question: str
    answer: str
    needle: str


def _choice(values: list[str]) -> str:
    return values[secrets.randbelow(len(values))]


def _generate_distractor_sentence(excluded_person: str) -> str:
    people = [person for person in PEOPLE if person != excluded_person]
    template = _choice(DISTRACTOR_TEMPLATES)
    return template.format(
        person=_choice(people),
        org=_choice(ORGANISATIONS),
        role=_choice(ROLES),
    )


def _normalize_answer(answer: str) -> str:
    without_punctuation = "".join(
        character for character in answer.lower().strip() if character not in string.punctuation
    )
    return " ".join(without_punctuation.split())


def _generate_needle_fact(used_questions: set[str] | None = None) -> _NeedleFact:
    """Generate one question, answer, and hidden needle sentence."""
    used_questions = used_questions if used_questions is not None else set()
    for _ in range(20):
        answer = _choice(PEOPLE)
        organisation = _choice(ORGANISATIONS)
        attribute = _choice(ATTRIBUTES)
        question = f"Which person in {organisation} has {attribute}?"
        if question not in used_questions:
            break
    else:
        answer = _choice(PEOPLE)
        organisation = _choice(ORGANISATIONS)
        attribute = _choice(ATTRIBUTES)
        question = f"Which person in {organisation} has {attribute}?"

    needle = f"The person in {organisation} who has {attribute} is {answer}."
    used_questions.add(question)
    return _NeedleFact(question=question, answer=answer, needle=needle)


def _generate_distractor_chunk(excluded_person: str, sentence_count: int) -> list[str]:
    return [
        _generate_distractor_sentence(excluded_person=excluded_person)
        for _ in range(sentence_count)
    ]


@router.post(
    "/create",
    response_model=CreateBenchmarkResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a majority-vote benchmark",
)
async def create_needlehaystack_benchmark(
    body: CreateBenchmarkRequest,
) -> CreateBenchmarkResponse:
    """Seed a strict majority of agents with the correct answer.

    The remaining agents receive a plausible-but-wrong needle (a different
    person from the same pool), so plurality voting can demonstrably beat
    the minority. Each agent's chunk also contains unrelated distractor
    sentences.
    """
    benchmark_id = str(uuid.uuid4())
    fact = _generate_needle_fact()

    # Strict majority: ceil((n + 1) / 2) — works for any n >= 2.
    correct_count = body.num_agents // 2 + 1
    incorrect_count = body.num_agents - correct_count

    # Pick which agents get the correct vs wrong needles. Shuffling agent
    # numbers (no positional bias) means the correct cluster isn't always
    # the first k agents.
    agent_numbers = list(range(1, body.num_agents + 1))
    for i in range(len(agent_numbers) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        agent_numbers[i], agent_numbers[j] = agent_numbers[j], agent_numbers[i]
    correct_agent_numbers = sorted(agent_numbers[:correct_count])
    incorrect_agent_numbers = sorted(agent_numbers[correct_count:])

    # Pick distinct wrong answers, one per misinformed agent.
    other_people = [person for person in PEOPLE if person != fact.answer]
    wrong_answers: list[str] = []
    for _ in range(incorrect_count):
        wrong_answers.append(other_people[secrets.randbelow(len(other_people))])

    chunks_by_agent: dict[str, list[str]] = {}
    for agent_number in range(1, body.num_agents + 1):
        agent_key = f"agent_{agent_number}"
        chunks_by_agent[agent_key] = _generate_distractor_chunk(
            excluded_person=fact.answer,
            sentence_count=body.sentences_per_agent,
        )

    # Insert the correct needle into each majority agent's chunk.
    for agent_number in correct_agent_numbers:
        agent_key = f"agent_{agent_number}"
        insert_position = secrets.randbelow(body.sentences_per_agent + 1)
        chunks_by_agent[agent_key].insert(insert_position, fact.needle)

    # Insert a wrong needle into each minority agent's chunk.
    for wrong_person, agent_number in zip(wrong_answers, incorrect_agent_numbers, strict=True):
        agent_key = f"agent_{agent_number}"
        wrong_needle = fact.needle.replace(fact.answer, wrong_person)
        insert_position = secrets.randbelow(body.sentences_per_agent + 1)
        chunks_by_agent[agent_key].insert(insert_position, wrong_needle)

    chunks = {agent_key: " ".join(sentences) for agent_key, sentences in chunks_by_agent.items()}
    correct_agent_keys = [f"agent_{n}" for n in correct_agent_numbers]
    BENCHMARKS[benchmark_id] = BenchmarkRecord(
        question=fact.question,
        answer=fact.answer,
        needle=fact.needle,
        correct_agents=correct_agent_keys,
        chunks=chunks,
    )

    return CreateBenchmarkResponse(
        benchmark_id=benchmark_id,
        question=fact.question,
        chunks=chunks,
        answer=fact.answer if body.include_answer else None,
        correct_agents=correct_agent_keys if body.include_answer else None,
        correct_agent_count=correct_count,
    )


@router.post(
    "/demo",
    response_model=CreateDemoBenchmarkResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an importable three-agent needle-in-a-haystack demo",
)
async def create_needlehaystack_demo(
    body: CreateDemoBenchmarkRequest,
) -> CreateDemoBenchmarkResponse:
    """Create a fixed three-agent canvas whose sources contain generated needles.

    Each generated question has exactly one owning agent/source. Agents without
    the relevant needle should answer ``unknown``, which plurality voting treats
    as zero score.
    """
    benchmark_id = str(uuid.uuid4())
    agent_ids = [str(template["id"]) for template in _DEMO_AGENT_TEMPLATES]
    source_ids = [str(template["id"]) for template in _DEMO_SOURCE_TEMPLATES]
    agent_keys = [f"agent_{n}" for n in range(1, _DEMO_AGENT_COUNT + 1)]
    chunks_by_agent: dict[str, list[str]] = {agent_key: [] for agent_key in agent_keys}
    needles: list[DemoNeedleRecord] = []
    used_questions: set[str] = set()

    for needle_index in range(body.num_needles):
        fact = _generate_needle_fact(used_questions)
        owner_index = needle_index % _DEMO_AGENT_COUNT

        for agent_index, agent_key in enumerate(agent_keys):
            sentences = _generate_distractor_chunk(
                excluded_person=fact.answer,
                sentence_count=body.sentences_per_needle,
            )
            if agent_index == owner_index:
                insert_position = secrets.randbelow(body.sentences_per_needle + 1)
                sentences.insert(insert_position, fact.needle)
            chunks_by_agent[agent_key].append(
                f"Generated context {needle_index + 1}:\n" + " ".join(sentences)
            )

        needles.append(
            DemoNeedleRecord(
                question=fact.question,
                answer=fact.answer,
                needle=fact.needle,
                agent_key=agent_keys[owner_index],
                agent_id=agent_ids[owner_index],
                source_id=source_ids[owner_index],
            )
        )

    agents: list[DemoCanvasAgent] = []
    sources: list[DemoCanvasSource] = []
    for _index, agent_template in enumerate(_DEMO_AGENT_TEMPLATES):
        agents.append(
            DemoCanvasAgent(
                id=str(agent_template["id"]),
                name=str(agent_template["name"]),
                description=str(agent_template["description"]),
                system_prompt=_DEMO_SYSTEM_PROMPT,
                provider="openai",
                model="gpt-4o-mini",
                tools=["files"],
                connections=list(agent_template["connections"]),
                position=agent_template["position"],
            )
        )

    for _index, source_template in enumerate(_DEMO_SOURCE_TEMPLATES):
        sources.append(
            DemoCanvasSource(
                id=str(source_template["id"]),
                name=str(source_template["name"]),
                type="text",
                content="\n\n".join(chunks_by_agent[agent_keys[_index]]),
                position=source_template["position"],
            )
        )

    edges = [
        DemoCanvasEdge(id=edge_id, from_id=from_id, to=to_id)
        for edge_id, from_id, to_id in _DEMO_EDGE_TEMPLATES
    ]
    demo = DemoCanvas(agents=agents, sources=sources, edges=edges)
    DEMO_BENCHMARKS[benchmark_id] = DemoBenchmarkRecord(demo=demo, needles=needles)

    return CreateDemoBenchmarkResponse(benchmark_id=benchmark_id, demo=demo)


@router.get(
    "/{benchmark_id}/needles",
    response_model=GetDemoBenchmarkNeedlesResponse,
    summary="Get questions, answers, and ownership for a generated demo benchmark",
)
async def get_needlehaystack_demo_needles(
    benchmark_id: str,
) -> GetDemoBenchmarkNeedlesResponse:
    record = DEMO_BENCHMARKS.get(benchmark_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Demo benchmark not found.",
        )
    return GetDemoBenchmarkNeedlesResponse(benchmark_id=benchmark_id, needles=record.needles)


@router.post(
    "/evaluate",
    response_model=EvaluateBenchmarkResponse,
    summary="Evaluate a generated answer for a majority-vote benchmark",
)
async def evaluate_needlehaystack_benchmark(
    body: EvaluateBenchmarkRequest,
) -> EvaluateBenchmarkResponse:
    record = BENCHMARKS.get(body.benchmark_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Benchmark not found.",
        )

    normalized_correct_answer = _normalize_answer(record.answer)
    normalized_generated_answer = _normalize_answer(body.generated_answer)

    # Substring match — voting answers are normalised aggressively (stop-words
    # stripped) so a bare "trump" still tallies, but the canonical answer may
    # contain a multi-word name like "mira novak". Match either direction.
    answer_correct = (
        normalized_generated_answer == normalized_correct_answer
        or normalized_correct_answer in normalized_generated_answer
        or normalized_generated_answer in normalized_correct_answer
    ) and bool(normalized_generated_answer)

    return EvaluateBenchmarkResponse(
        answer_correct=answer_correct,
        correct_answer=record.answer,
        generated_answer=body.generated_answer,
        normalized_correct_answer=normalized_correct_answer,
        normalized_generated_answer=normalized_generated_answer,
        correct_agents=record.correct_agents,
    )
