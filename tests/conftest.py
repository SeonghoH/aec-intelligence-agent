"""Shared pytest fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_notion_env(monkeypatch):
    """Ensure Notion env vars from the developer shell never leak into tests.

    Tests that need Notion env vars set should call monkeypatch.setenv()
    explicitly inside the test body — that overrides this default.
    """
    for var in (
        "NOTION_TOKEN",
        "NOTION_DAILY_DB_ID",
        "NOTION_RESEARCH_DB_ID",
        # LLM env vars must also be unset so tests don't accidentally hit
        # a live LLM provider via the developer's shell config.
        "LLM_ENABLED",
        "LLM_PROVIDER",
        "LLM_MODEL",
        "LLM_MAX_ITEMS",
        "LLM_MIN_SCORE",
        "LLM_MAX_CHARS",
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "UNPAYWALL_EMAIL",
    ):
        monkeypatch.delenv(var, raising=False)
