"""Readers backed by any chat model pydantic-ai supports (extra `[llm]`)."""
import os

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")  # pydantic-ai prints a banner to stdout on first use
