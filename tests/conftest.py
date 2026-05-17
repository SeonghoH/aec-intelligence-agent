"""Shared pytest fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_notion_env(monkeypatch):
    """Ensure Notion env vars from the developer shell never leak into tests.

    Tests that need Notion env vars set should call monkeypatch.setenv()
    explicitly inside the test body — that overrides this default.
    """
    for var in ("NOTION_TOKEN", "NOTION_DAILY_DB_ID", "NOTION_RESEARCH_DB_ID"):
        monkeypatch.delenv(var, raising=False)
