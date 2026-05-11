"""Needle-in-a-haystack benchmark routes."""

from __future__ import annotations

import secrets
import string
import uuid

from fastapi import APIRouter, HTTPException, status

from api.schemas import (
    BenchmarkRecord,
    CreateBenchmarkRequest,
    CreateBenchmarkResponse,
    EvaluateBenchmarkRequest,
    EvaluateBenchmarkResponse,
)

router = APIRouter(prefix="/benchmark/needlehaystack", tags=["Benchmarks"])

BENCHMARKS: dict[str, BenchmarkRecord] = {}

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
    answer = _choice(PEOPLE)
    organisation = _choice(ORGANISATIONS)
    attribute = _choice(ATTRIBUTES)
    question = f"Which person in {organisation} has {attribute}?"
    correct_needle = f"The person in {organisation} who has {attribute} is {answer}."

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
    other_people = [person for person in PEOPLE if person != answer]
    wrong_answers: list[str] = []
    for _ in range(incorrect_count):
        wrong_answers.append(other_people[secrets.randbelow(len(other_people))])

    chunks_by_agent: dict[str, list[str]] = {}
    for agent_number in range(1, body.num_agents + 1):
        agent_key = f"agent_{agent_number}"
        chunks_by_agent[agent_key] = [
            _generate_distractor_sentence(excluded_person=answer)
            for _ in range(body.sentences_per_agent)
        ]

    # Insert the correct needle into each majority agent's chunk.
    for agent_number in correct_agent_numbers:
        agent_key = f"agent_{agent_number}"
        insert_position = secrets.randbelow(body.sentences_per_agent + 1)
        chunks_by_agent[agent_key].insert(insert_position, correct_needle)

    # Insert a wrong needle into each minority agent's chunk.
    for wrong_person, agent_number in zip(wrong_answers, incorrect_agent_numbers, strict=True):
        agent_key = f"agent_{agent_number}"
        wrong_needle = f"The person in {organisation} who has {attribute} is {wrong_person}."
        insert_position = secrets.randbelow(body.sentences_per_agent + 1)
        chunks_by_agent[agent_key].insert(insert_position, wrong_needle)

    chunks = {agent_key: " ".join(sentences) for agent_key, sentences in chunks_by_agent.items()}
    correct_agent_keys = [f"agent_{n}" for n in correct_agent_numbers]
    BENCHMARKS[benchmark_id] = BenchmarkRecord(
        question=question,
        answer=answer,
        needle=correct_needle,
        correct_agents=correct_agent_keys,
        chunks=chunks,
    )

    return CreateBenchmarkResponse(
        benchmark_id=benchmark_id,
        question=question,
        chunks=chunks,
        answer=answer if body.include_answer else None,
        correct_agents=correct_agent_keys if body.include_answer else None,
        correct_agent_count=correct_count,
    )


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
