"""Langfuse SDK entry point.

Auto-initializes from environment variables when the first decorated function runs:
  LANGFUSE_SECRET_KEY  - secret key from your Langfuse project settings
  LANGFUSE_PUBLIC_KEY  - public key from your Langfuse project settings
  LANGFUSE_HOST        - base URL of your instance (default: https://cloud.langfuse.com)

When keys are absent the SDK runs in no-op mode - no errors, no logging.
"""

from langfuse.decorators import langfuse_context, observe

__all__ = ["langfuse_context", "observe"]
