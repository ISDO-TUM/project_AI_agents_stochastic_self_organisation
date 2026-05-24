"""Input sanitiser — detect and neutralise prompt-injection attempts.

Attack patterns mitigated
─────────────────────────
- Role/instruction overrides:  "Ignore previous instructions", "You are now…"
- Jailbreak framing:           "DAN mode", "developer mode", "act as if…"
- System prompt leakage probes: "reveal your prompt", "print your instructions"
- Delimiter smuggling:          raw <|im_start|> / [INST] tokens in user text
- Excessive repetition loops:   strings repeated 50+ times (resource exhaustion)
"""

from __future__ import annotations

import re
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Patterns that signal a prompt-injection attempt
# ---------------------------------------------------------------------------

_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    # Instruction override
    re.compile(
        r"\bignore\s+(all\s+)?(previous|prior|above|your)\s+(instructions?|prompts?|rules?|constraints?)\b",
        re.IGNORECASE,
    ),
    # Role switch
    re.compile(
        r"\b(you\s+are\s+now|act\s+as(\s+if)?|pretend\s+(you\s+are|to\s+be)|roleplay\s+as)\b",
        re.IGNORECASE,
    ),
    # Jailbreak modes
    re.compile(
        r"\b(DAN|jailbreak|developer\s+mode|unrestricted\s+mode|god\s+mode|no[-\s]filter)\b",
        re.IGNORECASE,
    ),
    # System prompt leakage
    re.compile(
        r"\b(reveal|print|output|show|repeat|display)\s+(your\s+)?(system\s+prompt|instructions?|rules?|initial\s+prompt)\b",
        re.IGNORECASE,
    ),
    # Delimiter token smuggling
    re.compile(
        r"(<\|im_(start|end|sep)\|>|\[INST\]|\[\/INST\]|<<SYS>>|<\/s>|<\|system\|>|<\|user\|>|<\|assistant\|>)",
        re.IGNORECASE,
    ),
    # Override via meta-instructions (allow up to 3 words between verb and target noun)
    re.compile(
        r"\b(disregard|forget|override|bypass|circumvent|disable)\b(\s+\w+){0,3}\s+(instructions?|guidelines?|rules?|safety|filters?|constraints?)\b",
        re.IGNORECASE,
    ),
    # Prompt-leak via indirect instruction
    re.compile(
        r"\bwhat\s+(is|are|were)\s+your\s+(original\s+)?(instructions?|system\s+prompt|rules?|guidelines?)\b",
        re.IGNORECASE,
    ),
]

# Excessive repetition: a token repeated more than 50 times in a row
_REPETITION_PATTERN = re.compile(r"(\b\S+\b)(\s+\1){49,}", re.IGNORECASE)


class PromptInjectionError(ValueError):
    """Raised when the input is detected as a prompt-injection attempt."""


class InputSanitizer:
    """Stateless sanitiser — call :meth:`sanitize` before passing text to an LLM."""

    def sanitize(self, text: str, field_name: str = "prompt") -> str:
        """Return *text* unchanged if safe, otherwise raise :exc:`PromptInjectionError`.

        Args:
            text: The raw user-supplied string.
            field_name: Human-readable name used in error messages.

        Raises:
            PromptInjectionError: If a known injection pattern is detected.
        """
        for pattern in _INJECTION_PATTERNS:
            if pattern.search(text):
                logger.warning(
                    "Prompt injection attempt detected in %s: pattern=%r excerpt=%r",
                    field_name,
                    pattern.pattern[:60],
                    text[:120],
                )
                raise PromptInjectionError(
                    f"The {field_name} contains a disallowed instruction-override pattern. "
                    "Please rephrase your request."
                )

        if _REPETITION_PATTERN.search(text):
            logger.warning(
                "Excessive repetition detected in %s (possible DoS): excerpt=%r",
                field_name,
                text[:120],
            )
            raise PromptInjectionError(
                f"The {field_name} contains an excessive repetition pattern. "
                "Please rephrase your request."
            )

        return text


# Module-level singleton for convenience
_sanitizer = InputSanitizer()


def sanitize_prompt(text: str, field_name: str = "prompt") -> str:
    """Convenience wrapper around :class:`InputSanitizer`."""
    return _sanitizer.sanitize(text, field_name)
