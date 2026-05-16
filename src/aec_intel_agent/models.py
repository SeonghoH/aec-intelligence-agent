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

    @property
    def display_date(self) -> str:
        """Return a stable date string for briefings."""

        if self.published_date is None:
            return "unknown date"
        return self.published_date.isoformat()

