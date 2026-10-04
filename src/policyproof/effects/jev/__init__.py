"""Readers backed by Jev, TypeSafe's decision model, through pydantic-ai (extra `[jev]`)."""
import os

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")  # pydantic-ai prints a banner to stdout on first use
