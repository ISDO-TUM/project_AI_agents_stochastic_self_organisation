import os

from groq import Groq

_client: Groq | None = None


def _get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=os.environ["GROQ_API_KEY"])
    return _client


def call_groq(prompt: str, model: str = "llama-3.3-70b-versatile") -> str:
    response = _get_client().chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content or ""
