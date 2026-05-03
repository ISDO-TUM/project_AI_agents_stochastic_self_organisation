"""Seed script - creates 3 example agents (one per provider) with knowledge files.

Usage:
    python -m api.tests.seed_agents [--base-url http://localhost:8000]

The script is idempotent in effect: each run creates fresh records (the
in-memory DB resets on server restart anyway).
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any

BASE_URL = "http://localhost:8000"


def _request(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{BASE_URL}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(  # noqa: S310
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:  # noqa: S310
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code} {method} {path}: {exc.read().decode()}", file=sys.stderr)
        raise


# ---------------------------------------------------------------------------
# Agent definitions
# ---------------------------------------------------------------------------

AGENTS: list[dict[str, Any]] = [
    {
        "name": "OpenAI Assistant",
        "description": "General-purpose assistant powered by OpenAI.",
        "system_prompt": (
            "You are a helpful assistant. When asked about files, use the "
            "file_access tool to read the relevant knowledge file before answering."
        ),
        "provider": "openai",
        "model": "gpt-4o-mini",
        "tools": ["files"],
        "connections": [],
    },
    {
        "name": "Anthropic Assistant",
        "description": "General-purpose assistant powered by Anthropic Claude.",
        "system_prompt": (
            "You are a knowledgeable assistant. Use the file_access tool whenever "
            "you need to consult a knowledge file to give an accurate answer."
        ),
        "provider": "anthropic",
        "model": "claude-haiku-4-5-20251001",
        "tools": ["files"],
        "connections": [],
    },
    {
        "name": "Groq Assistant",
        "description": "Fast assistant powered by Groq.",
        "system_prompt": (
            "You are a fast and concise assistant. Use the file_access tool to "
            "retrieve file contents when questions relate to stored knowledge."
        ),
        "provider": "groq",
        "model": "llama-3.1-8b-instant",
        "tools": ["files"],
        "connections": [],
    },
]

# ---------------------------------------------------------------------------
# Knowledge files - two per agent (keyed by provider name)
# ---------------------------------------------------------------------------

KNOWLEDGE_FILES: dict[str, list[dict[str, str]]] = {
    "openai": [
        {
            "name": "openai_product_faq.txt",
            "content": (
                "Q: What models does OpenAI offer?\n"
                "A: OpenAI offers GPT-4o, GPT-4o-mini, o1, and more.\n\n"
                "Q: What is the context window of GPT-4o?\n"
                "A: GPT-4o supports up to 128k tokens of context."
            ),
        },
        {
            "name": "openai_pricing.txt",
            "content": (
                "GPT-4o-mini: $0.15 per 1M input tokens, $0.60 per 1M output tokens.\n"
                "GPT-4o: $2.50 per 1M input tokens, $10.00 per 1M output tokens."
            ),
        },
    ],
    "anthropic": [
        {
            "name": "anthropic_product_faq.txt",
            "content": (
                "Q: What models does Anthropic offer?\n"
                "A: Anthropic offers Claude Opus, Sonnet, and Haiku model families.\n\n"
                "Q: What makes Claude different?\n"
                "A: Claude is designed with safety and helpfulness as core principles."
            ),
        },
        {
            "name": "anthropic_usage_policy.txt",
            "content": (
                "Claude may not be used to generate harmful content, assist in illegal "
                "activities, or deceive users. See anthropic.com/usage-policy for details."
            ),
        },
    ],
    "groq": [
        {
            "name": "groq_hardware_overview.txt",
            "content": (
                "Groq runs on the Language Processing Unit (LPU), purpose-built for "
                "inference. It delivers deterministic, low-latency token generation."
            ),
        },
        {
            "name": "groq_supported_models.txt",
            "content": (
                "Supported models on Groq:\n"
                "- llama-3.3-70b-versatile\n"
                "- llama-3.1-8b-instant\n"
                "- mixtral-8x7b-32768\n"
                "- gemma2-9b-it"
            ),
        },
    ],
}


def main(base_url: str) -> None:
    global BASE_URL
    BASE_URL = base_url.rstrip("/")

    print(f"Seeding against {BASE_URL}\n")

    for agent_def in AGENTS:
        provider = agent_def["provider"]

        # Create agent
        agent = _request("POST", "/api/agents/", agent_def)
        agent_id = agent["id"]
        print(f"[{provider}] Created agent '{agent['name']}' → {agent_id}")

        # Create knowledge files and attach them
        for file_def in KNOWLEDGE_FILES[provider]:
            kf = _request("POST", "/api/files/", file_def)
            file_id = kf["id"]
            _request("POST", f"/api/agents/{agent_id}/files/{file_id}")
            print(f"  Attached file '{kf['name']}' → {file_id}")

        print()

    print("Done. To run an agent:")
    print(f"  POST {BASE_URL}/api/agents/<agent_id>/run")
    print('  Body: {"prompt": "What files do you have?"}')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed example agents and knowledge files.")
    parser.add_argument("--base-url", default="http://localhost:8000", help="API base URL")
    args = parser.parse_args()
    main(args.base_url)
