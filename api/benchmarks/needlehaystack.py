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
    summary="Create a needle-in-a-haystack benchmark",
)
async def create_needlehaystack_benchmark(
    body: CreateBenchmarkRequest,
) -> CreateBenchmarkResponse:
    benchmark_id = str(uuid.uuid4())
    answer = _choice(PEOPLE)
    organisation = _choice(ORGANISATIONS)
    attribute = _choice(ATTRIBUTES)
    question = f"Which person in {organisation} has {attribute}?"
    needle = f"The person in {organisation} who has {attribute} is {answer}."

    chunks_by_agent: dict[str, list[str]] = {}
    for agent_number in range(1, body.num_agents + 1):
        agent_key = f"agent_{agent_number}"
        chunks_by_agent[agent_key] = [
            _generate_distractor_sentence(excluded_person=answer)
            for _ in range(body.sentences_per_agent)
        ]

    needle_agent = f"agent_{secrets.randbelow(body.num_agents) + 1}"
    insert_position = secrets.randbelow(body.sentences_per_agent + 1)
    chunks_by_agent[needle_agent].insert(insert_position, needle)

    chunks = {agent_key: " ".join(sentences) for agent_key, sentences in chunks_by_agent.items()}
    BENCHMARKS[benchmark_id] = BenchmarkRecord(
        question=question,
        answer=answer,
        needle=needle,
        needle_agent=needle_agent,
        chunks=chunks,
    )

    return CreateBenchmarkResponse(
        benchmark_id=benchmark_id,
        question=question,
        chunks=chunks,
        answer=answer if body.include_answer else None,
        needle_agent=needle_agent if body.include_answer else None,
    )


@router.post(
    "/evaluate",
    response_model=EvaluateBenchmarkResponse,
    summary="Evaluate a generated answer for a needle-in-a-haystack benchmark",
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
    routing_correct = (
        None if body.selected_agent is None else body.selected_agent == record.needle_agent
    )

    return EvaluateBenchmarkResponse(
        answer_correct=normalized_generated_answer == normalized_correct_answer,
        routing_correct=routing_correct,
        correct_answer=record.answer,
        generated_answer=body.generated_answer,
        normalized_correct_answer=normalized_correct_answer,
        normalized_generated_answer=normalized_generated_answer,
        needle_agent=record.needle_agent,
        selected_agent=body.selected_agent,
    )
