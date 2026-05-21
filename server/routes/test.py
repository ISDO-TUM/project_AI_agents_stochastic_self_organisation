"""Provider connectivity test routes, mounted at ``/api/test``."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from server.llm.anthropic_provider import call_anthropic
from server.llm.credentials import use_credentials
from server.llm.groq_provider import call_groq
from server.llm.openai_provider import call_openai
from server.schemas import (
    AnthropicPromptRequest,
    FilesToolRequest,
    FilesToolResponse,
    GroqPromptRequest,
    OpenAIPromptRequest,
    PromptResponse,
    ToolInfo,
)
from server.tools.builtin.files import FilesInput, FilesTool
from server.tools.registry import list_tools

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/test", tags=["Testing"])


@router.post(
    "/openai",
    response_model=PromptResponse,
    summary="Test OpenAI connectivity",
    dependencies=[Depends(use_credentials)],
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
    dependencies=[Depends(use_credentials)],
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
    dependencies=[Depends(use_credentials)],
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


@router.post(
    "/tools/files",
    response_model=FilesToolResponse,
    summary="Test files tool",
    description="Invoke the files handler directly with a mock file store.",
)
async def test_files_tool(body: FilesToolRequest) -> FilesToolResponse:
    tool = FilesTool()
    validated = FilesInput(action=body.action, file_name=body.file_name)
    result = await tool.execute(validated, {"files": body.files})
    return FilesToolResponse(result=result)
