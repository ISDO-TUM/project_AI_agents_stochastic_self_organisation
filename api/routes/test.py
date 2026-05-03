"""Provider connectivity test routes, mounted at ``/api/test``."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from api.llm.anthropic_provider import call_anthropic
from api.llm.groq_provider import call_groq
from api.llm.openai_provider import call_openai
from api.tools.builtin.file_access import handle as file_access_handle
from api.tools.registry import list_tools

logger = logging.getLogger(__name__)

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


class ToolInfo(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]


@router.post(
    "/openai",
    response_model=PromptResponse,
    summary="Test OpenAI connectivity",
)
async def test_openai(body: OpenAIPromptRequest) -> PromptResponse:
    try:
        result = await call_openai(body.prompt, model=body.model)
        return PromptResponse(response=result)
    except Exception as exc:
        logger.exception("OpenAI provider error")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "LLM provider unavailable") from exc


@router.post(
    "/anthropic",
    response_model=PromptResponse,
    summary="Test Anthropic connectivity",
)
async def test_anthropic(body: AnthropicPromptRequest) -> PromptResponse:
    try:
        result = await call_anthropic(body.prompt, model=body.model)
        return PromptResponse(response=result)
    except Exception as exc:
        logger.exception("Anthropic provider error")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "LLM provider unavailable") from exc


@router.post(
    "/groq",
    response_model=PromptResponse,
    summary="Test Groq connectivity",
)
async def test_groq(body: GroqPromptRequest) -> PromptResponse:
    try:
        result = await call_groq(body.prompt, model=body.model)
        return PromptResponse(response=result)
    except Exception as exc:
        logger.exception("Groq provider error")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "LLM provider unavailable") from exc


@router.get(
    "/tools",
    response_model=list[ToolInfo],
    summary="List available tools",
    description="Return all tools registered in the tool registry.",
)
async def get_tools() -> list[ToolInfo]:
    return [ToolInfo(**t) for t in list_tools()]


class FileAccessRequest(BaseModel):
    file_name: str = Field(..., description="Name of the file to read.")
    files: dict[str, str] = Field(..., description="Mock file store: name -> content.")


class FileAccessResponse(BaseModel):
    result: str


@router.post(
    "/tools/file-access",
    response_model=FileAccessResponse,
    summary="Test file_access tool",
    description="Invoke the file_access handler directly with a mock file store.",
)
async def test_file_access(body: FileAccessRequest) -> FileAccessResponse:
    result = file_access_handle(
        {"file_name": body.file_name},
        {"files": body.files},
    )
    return FileAccessResponse(result=result)
