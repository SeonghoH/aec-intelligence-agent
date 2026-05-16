"""Basic topic classification helpers."""

from __future__ import annotations

from typing import Any

from aec_intel_agent.models import StandardItem
from aec_intel_agent.scoring import _copy_item


def classify_item(item: StandardItem, keywords_config: dict[str, Any]) -> StandardItem:
    """Assign topics based on simple keyword presence."""

    text = f"{item.title} {item.summary}".lower()
    matched_topics: list[str] = []

    for topic, keywords in keywords_config.get("topics", {}).items():
        if any(keyword.lower() in text for keyword in keywords):
            matched_topics.append(topic)

    return _copy_item(item, {"topics": matched_topics})

