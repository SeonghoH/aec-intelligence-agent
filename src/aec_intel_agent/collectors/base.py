"""Base collector interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from aec_intel_agent.models import StandardItem


class BaseCollector(ABC):
    """Minimal collector contract."""

    name: str

    def __init__(self, keywords_config: dict[str, Any] | None = None) -> None:
        self.keywords_config = keywords_config or {}

    @abstractmethod
    def collect(self) -> list[StandardItem]:
        """Return normalized items."""
