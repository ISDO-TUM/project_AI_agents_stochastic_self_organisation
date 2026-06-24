"""Async HTTP client for the SAP-RPT tabular prediction API.

Wraps the two main RPT endpoints:
  - ``POST /api/predict``  — in-context tabular prediction
  - ``POST /api/chat``     — conversational natural-language interface

The client reads ``SAP_RPT_API_KEY`` and ``SAP_RPT_BASE_URL`` from the
environment at import time. Every public method returns typed dataclasses
so that callers never deal with raw HTTP responses.

Rate-limit handling
───────────────────
When the API returns 429 or 503 with a ``Retry-After`` header the client
waits and retries (up to ``max_retries`` times, default 2).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://rpt.cloud.sap"
_PREDICT_PATH = "/api/predict"
_CHAT_PATH = "/api/chat"

_TIMEOUT_SECONDS = 60
_MAX_RETRIES = 2


class RPTError(Exception):
    """Raised when an RPT API call fails after all retries."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"RPT API error {status_code}: {detail}")


# ── response dataclasses ──────────────────────────────────────────────────────


@dataclass
class RPTPredictionValue:
    """A single predicted value with an optional confidence score."""

    prediction: str
    confidence: float | None = None


@dataclass
class RPTPredictionRow:
    """Predictions for one query row, keyed by the index column (if any)."""

    index_value: str | None = None
    columns: dict[str, list[RPTPredictionValue]] = field(default_factory=dict)


@dataclass
class RPTPrediction:
    """Full response from ``POST /api/predict``."""

    id: str
    rows: list[RPTPredictionRow]
    num_predict_rows: int
    num_predict_tokens: int
    delay_ms: float


@dataclass
class RPTChatResponse:
    """Full response from ``POST /api/chat``."""

    content: str
    intent: str | None = None
    suggestions: list[dict[str, str]] = field(default_factory=list)
    timestamp: str | None = None


# ── client ────────────────────────────────────────────────────────────────────


def _get_config() -> tuple[str, str]:
    """Resolve RPT credentials for the current request.

    Precedence mirrors the LLM providers' BYOK story: the ``X-SAP-RPT-Key`` /
    ``X-SAP-RPT-Base-Url`` request headers (entered in the UI's API-keys modal)
    win, then the ``SAP_RPT_API_KEY`` / ``SAP_RPT_BASE_URL`` environment
    variables. Returns (base_url, api_key). Raises ``RuntimeError`` if no key is
    available — the caller (the tool) should catch this and return a
    user-friendly error string.
    """
    from server.llm.credentials import current_credentials

    creds = current_credentials()
    base_url = (creds.resolve_sap_rpt_base_url() or _DEFAULT_BASE_URL).rstrip("/")
    api_key = creds.resolve_sap_rpt_key()
    if not api_key:
        raise RuntimeError(
            "No SAP-RPT API key found. Enter it in the UI's API Keys dialog "
            "(SAP-RPT) or set SAP_RPT_API_KEY in your .env file."
        )
    return base_url, api_key


class RPTClient:
    """Stateless async client for the SAP-RPT API.

    Usage::

        client = RPTClient()
        prediction = await client.predict(
            rows=[
                {"customer_id": "C001", "age": 35, "churn": "No"},
                {"customer_id": "C002", "age": 28, "churn": "[PREDICT]"},
            ],
            index_column="customer_id",
        )
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        max_retries: int = _MAX_RETRIES,
    ) -> None:
        if base_url is None or api_key is None:
            env_url, env_key = _get_config()
            self._base_url = base_url or env_url
            self._api_key = api_key or env_key
        else:
            self._base_url = base_url.rstrip("/")
            self._api_key = api_key
        self._max_retries = max_retries

    # ── low-level HTTP ────────────────────────────────────────────────

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """POST with retry-on-429/503 logic."""
        url = f"{self._base_url}{path}"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        last_exc: Exception | None = None

        for attempt in range(1 + self._max_retries):
            try:
                async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                    resp = await client.post(url, json=body, headers=headers)

                    if resp.status_code in (429, 503):
                        retry_after = int(resp.headers.get("Retry-After", "5"))
                        if attempt < self._max_retries:
                            logger.warning(
                                "RPT %s returned %s — retrying in %ss (attempt %d/%d)",
                                path,
                                resp.status_code,
                                retry_after,
                                attempt + 1,
                                self._max_retries,
                            )
                            await asyncio.sleep(retry_after)
                            continue
                        raise RPTError(
                            resp.status_code, f"Rate-limited after {attempt + 1} attempts"
                        )

                    if resp.status_code >= 400:
                        detail = resp.text[:500]
                        raise RPTError(resp.status_code, detail)

                    return resp.json()  # type: ignore[no-any-return]

            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    await asyncio.sleep(2**attempt)
                    continue
                raise RPTError(0, f"HTTP transport error: {exc}") from exc

        # Should not reach here, but just in case
        raise RPTError(0, f"All retries exhausted: {last_exc}")

    # ── predict ───────────────────────────────────────────────────────

    async def predict(
        self,
        rows: list[dict[str, Any]],
        index_column: str | None = None,
    ) -> RPTPrediction:
        """Call ``POST /api/predict`` and return parsed results.

        Args:
            rows: Array of data rows. Context rows have complete data;
                  query rows contain ``[PREDICT]`` placeholders.
            index_column: Optional column name to use as row identifier.

        Returns:
            An ``RPTPrediction`` with typed prediction values and metadata.

        Raises:
            RPTError: On API failure after retries.
            RuntimeError: If ``SAP_RPT_API_KEY`` is not configured.
        """
        body: dict[str, Any] = {"rows": rows}
        if index_column:
            body["index_column"] = index_column

        data = await self._post(_PREDICT_PATH, body)
        prediction_data = data.get("prediction", data)

        # Parse prediction rows
        parsed_rows: list[RPTPredictionRow] = []
        for raw_row in prediction_data.get("predictions", []):
            row = RPTPredictionRow()
            for key, value in raw_row.items():
                if key == index_column:
                    row.index_value = str(value)
                elif isinstance(value, list):
                    row.columns[key] = [
                        RPTPredictionValue(
                            prediction=str(item.get("prediction", "")),
                            confidence=item.get("confidence"),
                        )
                        for item in value
                    ]
            parsed_rows.append(row)

        meta = prediction_data.get("metadata", {})
        return RPTPrediction(
            id=prediction_data.get("id", ""),
            rows=parsed_rows,
            num_predict_rows=meta.get("num_predict_rows", len(parsed_rows)),
            num_predict_tokens=meta.get("num_predict_tokens", 0),
            delay_ms=data.get("delay", 0.0),
        )

    # ── chat ──────────────────────────────────────────────────────────

    async def chat(
        self,
        messages: list[dict[str, str]],
        table_context: dict[str, Any] | None = None,
        conversation_context: dict[str, Any] | None = None,
    ) -> RPTChatResponse:
        """Call ``POST /api/chat`` and return parsed results.

        Args:
            messages: Conversation messages (role + content).
            table_context: Optional dataset metadata (columns, sample rows, etc.).
            conversation_context: Optional context from previous turns.

        Returns:
            An ``RPTChatResponse`` with the AI-generated content and suggestions.

        Raises:
            RPTError: On API failure after retries.
            RuntimeError: If ``SAP_RPT_API_KEY`` is not configured.
        """
        body: dict[str, Any] = {"messages": messages}
        if table_context:
            body["tableContext"] = table_context
        if conversation_context:
            body["conversationContext"] = conversation_context

        data = await self._post(_CHAT_PATH, body)
        return RPTChatResponse(
            content=data.get("content", ""),
            intent=data.get("intent"),
            suggestions=data.get("suggestions", []),
            timestamp=data.get("timestamp"),
        )

    # ── convenience: format predictions for agents ────────────────────

    @staticmethod
    def format_predictions(prediction: RPTPrediction) -> str:
        """Format an RPTPrediction into a human-readable string for LLM agents.

        The output includes prediction values, confidence scores, and metadata
        in a structured format that agents can reference in their reasoning.
        """
        lines: list[str] = [
            f"## RPT Prediction Results (id: {prediction.id})",
            f"- Rows predicted: {prediction.num_predict_rows}",
            f"- Processing time: {prediction.delay_ms:.0f}ms",
            "",
        ]
        for i, row in enumerate(prediction.rows):
            label = row.index_value or f"Row {i + 1}"
            lines.append(f"### {label}")
            for col_name, values in row.columns.items():
                for pv in values:
                    conf_str = (
                        f" (confidence: {pv.confidence:.2%})"
                        if pv.confidence is not None
                        else " (confidence: not available)"
                    )
                    lines.append(f"- **{col_name}**: {pv.prediction}{conf_str}")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def extract_max_confidence(prediction: RPTPrediction) -> float | None:
        """Extract the highest confidence score from a prediction result.

        Returns None if no confidence scores are available.
        This is useful for agents to calibrate their own deliberation confidence
        based on the RPT model's prediction confidence.
        """
        max_conf: float | None = None
        for row in prediction.rows:
            for values in row.columns.values():
                for pv in values:
                    if pv.confidence is not None:
                        if max_conf is None or pv.confidence > max_conf:
                            max_conf = pv.confidence
        return max_conf

    @staticmethod
    def extract_mean_confidence(prediction: RPTPrediction) -> float | None:
        """Extract the mean confidence score across all predictions.

        Returns None if no confidence scores are available.
        """
        scores: list[float] = []
        for row in prediction.rows:
            for values in row.columns.values():
                for pv in values:
                    if pv.confidence is not None:
                        scores.append(pv.confidence)
        if not scores:
            return None
        return sum(scores) / len(scores)
