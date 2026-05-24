"""Guardrails package.

Three layers of protection:

1. **InputSanitizer** – strips prompt-injection attempts before the prompt
   reaches the LLM (instruction overrides, role-switch markers, jailbreak
   patterns).

2. **PromptBuilder** – wraps every system prompt with anti-hallucination
   instructions so the model is explicitly told to stay grounded, admit
   uncertainty, and never fabricate citations.

3. **OutputValidator** – scans LLM output for signs of a successful
   injection attack or an unsafe/refused response and raises before the
   text is returned to the caller.
"""

from .input_sanitizer import InputSanitizer, sanitize_prompt
from .output_validator import OutputValidator, validate_llm_output
from .prompt_builder import build_guarded_system_prompt

__all__ = [
    "InputSanitizer",
    "sanitize_prompt",
    "OutputValidator",
    "validate_llm_output",
    "build_guarded_system_prompt",
]
