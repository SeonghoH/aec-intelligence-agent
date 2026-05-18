"""Shared data models for normalized intelligence items."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field


class StandardItem(BaseModel):
    """A normalized paper, article, or news item."""

    title: str
    source: str
    url: str | None = None
    item_type: str = "article"
    published_date: date | None = None
    authors: list[str] = Field(default_factory=list)
    summary: str = ""
    doi: str | None = None
    topics: list[str] = Field(default_factory=list)
    score: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)

    # Optional full-text discovery fields (set by the full_text module).
    full_text_status: str = "Not Attempted"
    full_text_url: str | None = None
    full_text_path: str | None = None

    @property
    def display_date(self) -> str:
        """Return a stable date string for briefings."""

        if self.published_date is None:
            return "unknown date"
        return self.published_date.isoformat()

