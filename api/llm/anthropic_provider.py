import os

from anthropic import Anthropic

_client: Anthropic | None = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def call_anthropic(prompt: str, model: str = "claude-haiku-4-5-20251001") -> str:
    response = _get_client().messages.create(
        model=model,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    block = response.content[0]
    return block.text if hasattr(block, "text") else ""
