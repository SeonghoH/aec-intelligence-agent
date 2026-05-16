"""Keyword scoring for normalized AEC intelligence items."""

from __future__ import annotations

from typing import Any

from aec_intel_agent.models import StandardItem


def _copy_item(item: StandardItem, updates: dict[str, Any]) -> StandardItem:
    """Copy a Pydantic model across Pydantic v1 and v2."""

    if hasattr(item, "model_copy"):
        return item.model_copy(update=updates)
    return item.copy(update=updates)


def _contains(text: str, keyword: str) -> bool:
    return keyword.lower() in text.lower()


def score_item(
    item: StandardItem,
    keywords_config: dict[str, Any],
    scoring_rules: dict[str, Any],
) -> StandardItem:
    """Score an item by keyword matches in the title and summary."""

    topics_config = keywords_config.get("topics", {})
    weights = scoring_rules.get("weights", {})
    title_weight = int(weights.get("title_keyword", 3))
    summary_weight = int(weights.get("summary_keyword", 1))
    topic_match_weight = int(weights.get("topic_match", 2))

    score = 0
    matched_topics: list[str] = []
    matched_keywords: list[str] = []

    for topic, keywords in topics_config.items():
        topic_score = 0
        for keyword in keywords:
            matched = False
            if _contains(item.title, keyword):
                topic_score += title_weight
                matched = True
            if item.summary and _contains(item.summary, keyword):
                topic_score += summary_weight
                matched = True
            if matched:
                matched_keywords.append(keyword)

        if topic_score:
            score += topic_score + topic_match_weight
            matched_topics.append(topic)

    metadata = {
        **item.metadata,
        "matched_keywords": sorted(set(matched_keywords), key=str.lower),
    }
    return _copy_item(
        item,
        {
            "score": score,
            "topics": matched_topics,
            "metadata": metadata,
        },
    )


def score_items(
    items: list[StandardItem],
    keywords_config: dict[str, Any],
    scoring_rules: dict[str, Any],
) -> list[StandardItem]:
    """Score and sort items with the highest score first."""

    scored_items = [
        score_item(item, keywords_config, scoring_rules)
        for item in items
    ]
    return sorted(scored_items, key=lambda item: item.score, reverse=True)

