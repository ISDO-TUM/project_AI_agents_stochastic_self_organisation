"""Output validator - scan LLM responses before returning them to callers.

Checks performed
----------------
1. **Injection echo** - the model repeats a verbatim injection trigger phrase,
   which is a strong signal that the injection succeeded.
2. **Refusal / safety block** - provider safety filters returned a refusal.
   We surface this as a structured error rather than silently passing it on.
3. **Empty / whitespace-only** - an empty response is useless and may indicate
   a misconfiguration or a successful jailbreak that silenced the model.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# Signs the model is parroting back an injected override
_ECHO_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bignore\s+(all\s+)?(previous|prior)\s+instructions?\b", re.IGNORECASE),
    re.compile(r"\byou\s+are\s+now\s+(a\s+|an\s+)?\w+\b", re.IGNORECASE),
    re.compile(r"\bDAN\s+mode\s+enabled\b", re.IGNORECASE),
    re.compile(
        r"\b(as\s+(a\s+|an\s+)?DAN|operating\s+in\s+developer\s+mode)\b", re.IGNORECASE
    ),
]

# Common provider refusal / content-policy phrases
_REFUSAL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"\b(I('m|\s+am)\s+)?(sorry|unable|not\s+able)\b.{0,60}\b(assist|help|fulfill|comply|provide)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(cannot|can't|won't|will\s+not)\s+(assist|help|provide|generate|create|produce)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(violates?|against)\s+(my\s+)?(guidelines?|policies?|terms|safety)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bI\s+don't\s+have\s+the\s+ability\s+to\b", re.IGNORECASE),
]


class LLMRefusalError(ValueError):
    """Raised when the LLM output is detected as a content-policy refusal."""


class InjectionEchoError(ValueError):
    """Raised when the LLM output echoes a prompt-injection instruction."""


class OutputValidator:
    """Validates raw LLM output before it is forwarded to the caller."""

    def validate(self, text: str) -> str:
        """Return *text* if it passes all checks, otherwise raise.

        Args:
            text: Raw LLM response string.

        Returns:
            The original *text*, unchanged.

        Raises:
            InjectionEchoError: If the output echoes a known injection phrase.
            LLMRefusalError: If the output is a content-policy refusal.
            ValueError: If the output is empty.
        """
        stripped = text.strip()

        if not stripped:
            raise ValueError(
                "The LLM returned an empty response. "
                "Please rephrase your prompt or try again."
            )

        for pattern in _ECHO_INJECTION_PATTERNS:
            if pattern.search(stripped):
                logger.warning(
                    "Injection echo detected in LLM output: pattern=%r excerpt=%r",
                    pattern.pattern[:60],
                    stripped[:120],
                )
                raise InjectionEchoError(
                    "The model response was flagged as potentially unsafe "
                    "(injection echo detected). The response has been suppressed."
                )

        for pattern in _REFUSAL_PATTERNS:
            if pattern.search(stripped):
                logger.info(
                    "LLM refusal detected in output: excerpt=%r", stripped[:120]
                )
                raise LLMRefusalError(
                    "The model declined to answer this request. "
                    "Please rephrase your prompt or adjust the agent's configuration."
                )

        return text


# Module-level singleton
_validator = OutputValidator()


def validate_llm_output(text: str) -> str:
    """Convenience wrapper around :class:`OutputValidator`."""
    return _validator.validate(text)
