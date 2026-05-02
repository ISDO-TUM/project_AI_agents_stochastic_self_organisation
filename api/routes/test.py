"""Provider connectivity test routes, mounted at ``/api/test``."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from api.llm.anthropic_provider import call_anthropic
from api.llm.groq_provider import call_groq
from api.llm.openai_provider import call_openai

router = APIRouter(prefix="/api/test", tags=["Testing"])

OPENAI_DEFAULT_MODEL = "gpt-4.1-nano"
ANTHROPIC_DEFAULT_MODEL = "claude-haiku-4-5-20251001"
GROQ_DEFAULT_MODEL = "llama-3.1-8b-instant"


class OpenAIPromptRequest(BaseModel):
    prompt: str = Field(..., examples=["Hello"])
    model: str = Field(OPENAI_DEFAULT_MODEL, examples=[OPENAI_DEFAULT_MODEL])


class AnthropicPromptRequest(BaseModel):
    prompt: str = Field(..., examples=["Hello"])
    model: str = Field(ANTHROPIC_DEFAULT_MODEL, examples=[ANTHROPIC_DEFAULT_MODEL])


class GroqPromptRequest(BaseModel):
    prompt: str = Field(..., examples=["Hello"])
    model: str = Field(GROQ_DEFAULT_MODEL, examples=[GROQ_DEFAULT_MODEL])


class PromptResponse(BaseModel):
    response: str


@router.post(
    "/openai",
    response_model=PromptResponse,
    summary="Test OpenAI connectivity",
)
async def test_openai(body: OpenAIPromptRequest) -> PromptResponse:
    try:
        return PromptResponse(response=call_openai(body.prompt, model=body.model))
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@router.post(
    "/anthropic",
    response_model=PromptResponse,
    summary="Test Anthropic connectivity",
)
async def test_anthropic(body: AnthropicPromptRequest) -> PromptResponse:
    try:
        return PromptResponse(response=call_anthropic(body.prompt, model=body.model))
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@router.post(
    "/groq",
    response_model=PromptResponse,
    summary="Test Groq connectivity",
)
async def test_groq(body: GroqPromptRequest) -> PromptResponse:
    try:
        return PromptResponse(response=call_groq(body.prompt, model=body.model))
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
