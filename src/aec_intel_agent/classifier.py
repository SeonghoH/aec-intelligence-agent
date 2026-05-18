"""Topic classification with relevance gating.

The classifier decides which topics a paper "belongs to" based on keyword
presence. One important rule: the `embodied_carbon` (LCA) topic is gated —
a paper that matches `LCA` alone but is about food / biodiesel / coffee
packaging / aviation should NOT be classified as LCA. To be classified,
the paper must ALSO mention a construction-domain keyword and must NOT be
dominated by an LCA-negative keyword.

The scoring module reads `topics` from the classified item, so this gate
also controls the topic-match bonus and the briefing's section routing.
"""

from __future__ import annotations

from typing import Any

from aec_intel_agent.models import StandardItem
from aec_intel_agent.scoring import _copy_item

LCA_TOPIC = "embodied_carbon"


def _text(item: StandardItem) -> str:
    return f"{item.title or ''} {item.summary or ''}".lower()


def _has_any(text: str, terms: list[str]) -> bool:
    return any(t.lower() in text for t in terms if t)


def is_construction_related(
    item: StandardItem, keywords_config: dict[str, Any]
) -> bool:
    """True if the item mentions any construction-domain keyword."""
    domain = keywords_config.get("construction_domain_keywords") or []
    return _has_any(_text(item), list(domain))


def has_lca_negative_signal(
    item: StandardItem, keywords_config: dict[str, Any]
) -> bool:
    """True if the item contains an LCA-negative keyword (food, biofuel, etc.)."""
    negatives = keywords_config.get("lca_negative_keywords") or []
    return _has_any(_text(item), list(negatives))


def lca_passes_gate(item: StandardItem, keywords_config: dict[str, Any]) -> bool:
    """Decide whether an LCA-matched item should keep the LCA topic.

    Rules:
    - Must have at least one construction-domain keyword.
    - Must not have an LCA-negative keyword UNLESS construction context is
      explicitly present (e.g. "concrete fuel ash" — keep, because concrete
      wins). We implement the simpler rule: any negative kills LCA unless
      a strong construction term ("building", "construction", "structural",
      "concrete", "steel", "infrastructure", "façade", "facade") is also
      present.
    """
    if not is_construction_related(item, keywords_config):
        return False

    if has_lca_negative_signal(item, keywords_config):
        text = _text(item)
        strong = ["building", "construction", "structural", "concrete",
                  "steel", "infrastructure", "façade", "facade"]
        if not any(t in text for t in strong):
            return False
    return True


def classify_item(item: StandardItem, keywords_config: dict[str, Any]) -> StandardItem:
    """Assign topics based on keyword presence with an LCA gate."""

    text = _text(item)
    matched_topics: list[str] = []

    for topic, keywords in keywords_config.get("topics", {}).items():
        if not any(keyword.lower() in text for keyword in keywords):
            continue
        if topic == LCA_TOPIC and not lca_passes_gate(item, keywords_config):
            continue
        matched_topics.append(topic)

    return _copy_item(item, {"topics": matched_topics})
