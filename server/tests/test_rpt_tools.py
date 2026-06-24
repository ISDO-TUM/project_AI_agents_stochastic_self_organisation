"""Tests for the RPT tools (rpt_predict and rpt_chat) and client.

These tests mock the HTTP layer so they never hit the real SAP-RPT API.
They verify:
  - Input validation (missing rows, too few context rows, bad JSON)
  - Correct API payload construction
  - Response parsing (predictions, confidence scores, metadata)
  - Error handling (RPT API errors, missing config)
  - Confidence extraction helpers
  - Tool schema generation for all LLM providers
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from server.rpt.client import (
    RPTChatResponse,
    RPTClient,
    RPTError,
    RPTPrediction,
    RPTPredictionRow,
    RPTPredictionValue,
)
from server.tools.builtin.rpt_chat import RPTChatInput, RPTChatTool
from server.tools.builtin.rpt_predict import RPTPredictInput, RPTPredictTool

# ── fixtures ──────────────────────────────────────────────────────────────────

SAMPLE_PREDICT_RESPONSE = {
    "prediction": {
        "id": "test-pred-001",
        "metadata": {
            "num_columns": 3,
            "num_predict_rows": 1,
            "num_predict_tokens": 1,
            "num_rows": 2,
        },
        "predictions": [
            {
                "equipment_id": "E003",
                "rul_days": [{"confidence": 0.82, "prediction": "45"}],
            }
        ],
    },
    "delay": 1250.5,
}

SAMPLE_PREDICT_RESPONSE_NO_CONFIDENCE = {
    "prediction": {
        "id": "test-pred-002",
        "metadata": {
            "num_columns": 2,
            "num_predict_rows": 1,
            "num_predict_tokens": 1,
            "num_rows": 2,
        },
        "predictions": [
            {
                "customer_id": "C002",
                "churn": [{"confidence": None, "prediction": "Yes"}],
            }
        ],
    },
    "delay": 900.0,
}

SAMPLE_CHAT_RESPONSE = {
    "content": (
        "Reducing quantity by 20% across all orders is predicted to decrease "
        "CO2 emissions by approximately 15%."
    ),
    "timestamp": "2026-04-29T10:30:45.123Z",
    "intent": "WHAT_IF",
    "suggestions": [
        {"label": "Try a different reduction", "query": "What if I reduce by 30%?"},
        {"label": "Check accuracy", "query": "Test model accuracy for CO2"},
    ],
}


EQUIPMENT_ROWS = [
    {
        "equipment_id": "E001",
        "operating_hours": 8500,
        "vibration": 2.1,
        "rul_days": 120,
    },
    {
        "equipment_id": "E002",
        "operating_hours": 12000,
        "vibration": 4.8,
        "rul_days": 30,
    },
    {
        "equipment_id": "E003",
        "operating_hours": 9200,
        "vibration": 3.5,
        "rul_days": "[PREDICT]",
    },
]


@pytest.fixture()
def predict_tool() -> RPTPredictTool:
    return RPTPredictTool()


@pytest.fixture()
def chat_tool() -> RPTChatTool:
    return RPTChatTool()


# ── RPTClient unit tests ─────────────────────────────────────────────────────


class TestRPTClient:
    """Test the RPTClient response parsing and helper methods."""

    @pytest.mark.asyncio()
    async def test_predict_parses_response(self) -> None:
        """Predict returns typed RPTPrediction with correct fields."""
        with patch.dict("os.environ", {"SAP_RPT_API_KEY": "test-key"}):
            client = RPTClient()
            client._post = AsyncMock(return_value=SAMPLE_PREDICT_RESPONSE)

            result = await client.predict(rows=EQUIPMENT_ROWS, index_column="equipment_id")

            assert isinstance(result, RPTPrediction)
            assert result.id == "test-pred-001"
            assert result.num_predict_rows == 1
            assert result.delay_ms == 1250.5
            assert len(result.rows) == 1
            assert result.rows[0].index_value == "E003"
            assert "rul_days" in result.rows[0].columns
            pv = result.rows[0].columns["rul_days"][0]
            assert pv.prediction == "45"
            assert pv.confidence == 0.82

    @pytest.mark.asyncio()
    async def test_predict_sends_correct_payload(self) -> None:
        """Predict passes rows and index_column to the API."""
        with patch.dict("os.environ", {"SAP_RPT_API_KEY": "test-key"}):
            client = RPTClient()
            client._post = AsyncMock(return_value=SAMPLE_PREDICT_RESPONSE)

            await client.predict(rows=EQUIPMENT_ROWS, index_column="equipment_id")

            client._post.assert_called_once()
            call_args = client._post.call_args
            assert call_args[0][0] == "/api/predict"
            body = call_args[0][1]
            assert body["rows"] == EQUIPMENT_ROWS
            assert body["index_column"] == "equipment_id"

    @pytest.mark.asyncio()
    async def test_chat_parses_response(self) -> None:
        """Chat returns typed RPTChatResponse with correct fields."""
        with patch.dict("os.environ", {"SAP_RPT_API_KEY": "test-key"}):
            client = RPTClient()
            client._post = AsyncMock(return_value=SAMPLE_CHAT_RESPONSE)

            result = await client.chat(
                messages=[{"role": "user", "content": "What if I reduce quantity?"}]
            )

            assert isinstance(result, RPTChatResponse)
            assert "15%" in result.content
            assert result.intent == "WHAT_IF"
            assert len(result.suggestions) == 2

    def test_format_predictions(self) -> None:
        """format_predictions produces a human-readable markdown string."""
        prediction = RPTPrediction(
            id="test-001",
            rows=[
                RPTPredictionRow(
                    index_value="E003",
                    columns={"rul_days": [RPTPredictionValue(prediction="45", confidence=0.82)]},
                )
            ],
            num_predict_rows=1,
            num_predict_tokens=1,
            delay_ms=1000.0,
        )
        formatted = RPTClient.format_predictions(prediction)
        assert "E003" in formatted
        assert "rul_days" in formatted
        assert "45" in formatted
        assert "82.00%" in formatted

    def test_format_predictions_no_confidence(self) -> None:
        """format_predictions handles None confidence gracefully."""
        prediction = RPTPrediction(
            id="test-002",
            rows=[
                RPTPredictionRow(
                    index_value="C002",
                    columns={"churn": [RPTPredictionValue(prediction="Yes", confidence=None)]},
                )
            ],
            num_predict_rows=1,
            num_predict_tokens=1,
            delay_ms=500.0,
        )
        formatted = RPTClient.format_predictions(prediction)
        assert "not available" in formatted

    def test_extract_max_confidence(self) -> None:
        """extract_max_confidence returns the highest score."""
        prediction = RPTPrediction(
            id="test",
            rows=[
                RPTPredictionRow(
                    columns={
                        "col_a": [
                            RPTPredictionValue(prediction="X", confidence=0.7),
                            RPTPredictionValue(prediction="Y", confidence=0.9),
                        ],
                        "col_b": [RPTPredictionValue(prediction="Z", confidence=0.8)],
                    }
                )
            ],
            num_predict_rows=1,
            num_predict_tokens=2,
            delay_ms=0,
        )
        assert RPTClient.extract_max_confidence(prediction) == 0.9

    def test_extract_max_confidence_none(self) -> None:
        """extract_max_confidence returns None when no scores exist."""
        prediction = RPTPrediction(
            id="test",
            rows=[
                RPTPredictionRow(
                    columns={"col": [RPTPredictionValue(prediction="X", confidence=None)]}
                )
            ],
            num_predict_rows=1,
            num_predict_tokens=1,
            delay_ms=0,
        )
        assert RPTClient.extract_max_confidence(prediction) is None

    def test_extract_mean_confidence(self) -> None:
        """extract_mean_confidence returns the average across all values."""
        prediction = RPTPrediction(
            id="test",
            rows=[
                RPTPredictionRow(
                    columns={
                        "col": [
                            RPTPredictionValue(prediction="A", confidence=0.6),
                            RPTPredictionValue(prediction="B", confidence=0.8),
                        ]
                    }
                )
            ],
            num_predict_rows=1,
            num_predict_tokens=2,
            delay_ms=0,
        )
        assert RPTClient.extract_mean_confidence(prediction) == pytest.approx(0.7)

    @pytest.mark.asyncio()
    async def test_missing_api_key_raises(self) -> None:
        """Client raises RuntimeError when SAP_RPT_API_KEY is unset."""
        with patch.dict("os.environ", {}, clear=True):
            # Remove the key entirely
            import os

            os.environ.pop("SAP_RPT_API_KEY", None)
            with pytest.raises(RuntimeError, match="SAP_RPT_API_KEY"):
                RPTClient()


# ── RPTPredictTool unit tests ────────────────────────────────────────────────


class TestRPTPredictTool:
    """Test the rpt_predict tool input validation and execution."""

    @pytest.mark.asyncio()
    async def test_invalid_json_rows(self, predict_tool: RPTPredictTool) -> None:
        """Bad JSON in rows returns a user-friendly error."""
        inp = RPTPredictInput(rows="not valid json")
        result = await predict_tool.execute(inp)
        assert "Invalid JSON" in result

    @pytest.mark.asyncio()
    async def test_empty_rows(self, predict_tool: RPTPredictTool) -> None:
        """Empty array returns an error."""
        inp = RPTPredictInput(rows="[]")
        result = await predict_tool.execute(inp)
        assert "non-empty" in result

    @pytest.mark.asyncio()
    async def test_no_predict_placeholder(self, predict_tool: RPTPredictTool) -> None:
        """Rows without [PREDICT] return an error."""
        rows = json.dumps(
            [
                {"id": "1", "val": "a"},
                {"id": "2", "val": "b"},
                {"id": "3", "val": "c"},
            ]
        )
        inp = RPTPredictInput(rows=rows)
        result = await predict_tool.execute(inp)
        assert "[PREDICT]" in result

    @pytest.mark.asyncio()
    async def test_too_few_context_rows(self, predict_tool: RPTPredictTool) -> None:
        """Only one context row returns an error (need >= 2)."""
        rows = json.dumps(
            [
                {"id": "1", "val": "a"},
                {"id": "2", "val": "[PREDICT]"},
            ]
        )
        inp = RPTPredictInput(rows=rows)
        result = await predict_tool.execute(inp)
        assert "context row" in result.lower()

    @pytest.mark.asyncio()
    async def test_successful_prediction(self, predict_tool: RPTPredictTool) -> None:
        """Successful predict call returns formatted results with confidence."""
        mock_prediction = RPTPrediction(
            id="test-001",
            rows=[
                RPTPredictionRow(
                    index_value="E003",
                    columns={"rul_days": [RPTPredictionValue(prediction="45", confidence=0.82)]},
                )
            ],
            num_predict_rows=1,
            num_predict_tokens=1,
            delay_ms=1000.0,
        )
        with patch("server.rpt.client.RPTClient") as mock_client_cls:
            mock_instance = mock_client_cls.return_value
            mock_instance.predict = AsyncMock(return_value=mock_prediction)
            mock_client_cls.format_predictions = RPTClient.format_predictions
            mock_client_cls.extract_mean_confidence = RPTClient.extract_mean_confidence

            inp = RPTPredictInput(
                rows=json.dumps(EQUIPMENT_ROWS),
                index_column="equipment_id",
            )
            result = await predict_tool.execute(inp)

            assert "E003" in result
            assert "45" in result
            assert "82.00%" in result
            assert "deliberation" in result.lower()

    @pytest.mark.asyncio()
    async def test_rpt_api_error(self, predict_tool: RPTPredictTool) -> None:
        """RPTError from the client is caught and returned as a string."""
        with patch("server.rpt.client.RPTClient") as mock_client_cls:
            mock_instance = mock_client_cls.return_value
            mock_instance.predict = AsyncMock(side_effect=RPTError(400, "Invalid data format"))

            inp = RPTPredictInput(
                rows=json.dumps(EQUIPMENT_ROWS),
                index_column="equipment_id",
            )
            result = await predict_tool.execute(inp)
            assert "failed" in result.lower()

    @pytest.mark.asyncio()
    async def test_missing_config_error(self, predict_tool: RPTPredictTool) -> None:
        """RuntimeError (missing API key) is returned as a config error."""
        with patch("server.rpt.client.RPTClient") as mock_client_cls:
            mock_client_cls.side_effect = RuntimeError("SAP_RPT_API_KEY is not set")

            inp = RPTPredictInput(
                rows=json.dumps(EQUIPMENT_ROWS),
                index_column="equipment_id",
            )
            result = await predict_tool.execute(inp)
            assert "configuration" in result.lower() or "SAP_RPT_API_KEY" in result

    def test_tool_schema_openai(self, predict_tool: RPTPredictTool) -> None:
        """OpenAI-formatted schema has the expected shape."""
        schema = predict_tool.to_openai()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "rpt_predict"
        assert "rows" in schema["function"]["parameters"]["properties"]

    def test_tool_schema_anthropic(self, predict_tool: RPTPredictTool) -> None:
        """Anthropic-formatted schema has the expected shape."""
        schema = predict_tool.to_anthropic()
        assert schema["name"] == "rpt_predict"
        assert "rows" in schema["input_schema"]["properties"]

    def test_tool_schema_gemini(self, predict_tool: RPTPredictTool) -> None:
        """Gemini-formatted schema strips $defs."""
        schema = predict_tool.to_gemini()
        assert schema["name"] == "rpt_predict"
        assert "$defs" not in schema["parameters"]


# ── RPTChatTool unit tests ───────────────────────────────────────────────────


class TestRPTChatTool:
    """Test the rpt_chat tool input validation and execution."""

    @pytest.mark.asyncio()
    async def test_empty_question(self, chat_tool: RPTChatTool) -> None:
        """Empty question returns an error."""
        inp = RPTChatInput(question="   ")
        result = await chat_tool.execute(inp)
        assert "non-empty" in result.lower()

    @pytest.mark.asyncio()
    async def test_invalid_table_context_json(self, chat_tool: RPTChatTool) -> None:
        """Bad JSON in table_context returns an error."""
        inp = RPTChatInput(question="What is the average?", table_context="not json")
        result = await chat_tool.execute(inp)
        assert "Invalid JSON" in result

    @pytest.mark.asyncio()
    async def test_successful_chat(self, chat_tool: RPTChatTool) -> None:
        """Successful chat call returns formatted results."""
        mock_response = RPTChatResponse(
            content="CO2 emissions would decrease by 15%.",
            intent="WHAT_IF",
            suggestions=[{"label": "Try more", "query": "What if 30%?"}],
            timestamp="2026-01-01T00:00:00Z",
        )
        with patch("server.rpt.client.RPTClient") as mock_client_cls:
            mock_instance = mock_client_cls.return_value
            mock_instance.chat = AsyncMock(return_value=mock_response)

            inp = RPTChatInput(
                question="What if I reduce quantity by 20%?",
                table_context=json.dumps({"columns": ["Qty", "CO2"], "rowCount": 100}),
            )
            result = await chat_tool.execute(inp)

            assert "15%" in result
            assert "WHAT_IF" in result
            assert "Try more" in result

    @pytest.mark.asyncio()
    async def test_chat_without_table_context(self, chat_tool: RPTChatTool) -> None:
        """Chat works without table_context for data questions."""
        mock_response = RPTChatResponse(
            content="The average is 42.",
            intent="DATA_QUESTION",
        )
        with patch("server.rpt.client.RPTClient") as mock_client_cls:
            mock_instance = mock_client_cls.return_value
            mock_instance.chat = AsyncMock(return_value=mock_response)

            inp = RPTChatInput(question="What is the average?")
            result = await chat_tool.execute(inp)

            assert "42" in result

    def test_tool_schema_openai(self, chat_tool: RPTChatTool) -> None:
        """OpenAI-formatted schema has the expected shape."""
        schema = chat_tool.to_openai()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "rpt_chat"
        assert "question" in schema["function"]["parameters"]["properties"]


# ── Tool registration test ───────────────────────────────────────────────────


class TestRPTToolRegistration:
    """Verify that RPT tools are registered in the global registry."""

    def test_rpt_predict_registered(self) -> None:
        from server.tools.registry import get_tool

        tool = get_tool("rpt_predict")
        assert tool is not None
        assert isinstance(tool, RPTPredictTool)

    def test_rpt_chat_registered(self) -> None:
        from server.tools.registry import get_tool

        tool = get_tool("rpt_chat")
        assert tool is not None
        assert isinstance(tool, RPTChatTool)

    def test_list_tools_includes_rpt(self) -> None:
        from server.tools.registry import list_tools

        tools = list_tools()
        names = {t["name"] for t in tools}
        assert "rpt_predict" in names
        assert "rpt_chat" in names

    def test_provider_format_openai(self) -> None:
        from server.tools.registry import get_tools_for_provider

        tools = get_tools_for_provider("openai", ["rpt_predict", "rpt_chat"])
        assert len(tools) == 2
        assert tools[0]["function"]["name"] == "rpt_predict"
        assert tools[1]["function"]["name"] == "rpt_chat"

    def test_provider_format_anthropic(self) -> None:
        from server.tools.registry import get_tools_for_provider

        tools = get_tools_for_provider("anthropic", ["rpt_predict", "rpt_chat"])
        assert len(tools) == 2
        assert tools[0]["name"] == "rpt_predict"

    def test_provider_format_gemini(self) -> None:
        from server.tools.registry import get_tools_for_provider

        tools = get_tools_for_provider("gemini", ["rpt_predict"])
        assert len(tools) == 1
        assert "$defs" not in tools[0]["parameters"]
