"""Keyword scoring for normalized AEC intelligence items.

Scoring respects the same LCA construction-domain gate as the classifier:
an `embodied_carbon` keyword match contributes raw keyword points (title /
summary), but the topic-match bonus and the `topics` list entry are only
awarded if the item also has a construction-domain co-occurrence. Off-topic
LCA (food, biodiesel, coffee packaging, etc.) therefore stays below the
relevance thresholds.
"""

from __future__ import annotations

from typing import Any

from aec_intel_agent.models import StandardItem

LCA_TOPIC = "embodied_carbon"

# Penalty per LCA-negative keyword hit when the LCA gate also fails.
# Keeps food / biofuel / coffee / aviation LCA below the minimum_score
# threshold, removing them from the briefing entirely.
LCA_NEGATIVE_PENALTY_PER_HIT = 15


def _copy_item(item: StandardItem, updates: dict[str, Any]) -> StandardItem:
    """Copy a Pydantic model across Pydantic v1 and v2."""

    if hasattr(item, "model_copy"):
        return item.model_copy(update=updates)
    return item.copy(update=updates)


def _contains(text: str, keyword: str) -> bool:
    return keyword.lower() in text.lower()


def _lca_passes_gate(item: StandardItem, keywords_config: dict[str, Any]) -> bool:
    """Local copy of the classifier gate, to avoid an import cycle."""
    text = f"{item.title or ''} {item.summary or ''}".lower()
    domain = keywords_config.get("construction_domain_keywords") or []
    negatives = keywords_config.get("lca_negative_keywords") or []

    construction_hit = any(d.lower() in text for d in domain if d)
    if not construction_hit:
        return False

    negative_hit = any(n.lower() in text for n in negatives if n)
    if negative_hit:
        strong = ("building", "construction", "structural", "concrete",
                  "steel", "infrastructure", "façade", "facade")
        if not any(s in text for s in strong):
            return False
    return True


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

        if not topic_score:
            continue

        # LCA must clear the construction-domain gate to count as a topic
        # match (no topic bonus, no `topics` list entry). Raw keyword
        # points still accrue so we don't completely lose the signal.
        if topic == LCA_TOPIC and not _lca_passes_gate(item, keywords_config):
            score += topic_score  # no topic_match_weight, no topic label
            continue

        score += topic_score + topic_match_weight
        matched_topics.append(topic)

    # Heavy downscore for off-topic LCA items: any negative keyword hit
    # (food, biodiesel, coffee, aviation, wastewater, …) costs points,
    # but only when the construction gate has also failed (i.e. there is
    # no construction context to justify keeping the paper).
    if LCA_TOPIC not in matched_topics:
        text = f"{item.title or ''} {item.summary or ''}".lower()
        negatives = keywords_config.get("lca_negative_keywords") or []
        hits = sum(1 for n in negatives if n and n.lower() in text)
        if hits:
            score -= hits * LCA_NEGATIVE_PENALTY_PER_HIT
            score = max(score, 0)

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

