"""Relevance-tuning tests: LCA gating, steel routing, full-text eligibility."""

from __future__ import annotations

from aec_intel_agent.briefing import generate_markdown_briefing
from aec_intel_agent.classifier import classify_item
from aec_intel_agent.config_loader import load_config
from aec_intel_agent.full_text import select_candidates
from aec_intel_agent.models import StandardItem
from aec_intel_agent.scoring import score_item


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _config():
    """Load the real project config to keep the test honest."""
    return load_config("config")


def _keywords():
    return _config()["keywords"]


def _scoring_rules():
    return _config()["scoring_rules"]


def _item(**kw) -> StandardItem:
    defaults = {"title": "T", "source": "test"}
    return StandardItem(**{**defaults, **kw})


def _section_text(md: str, header: str) -> str:
    import re
    parts = md.split(f"## {header}")
    assert len(parts) >= 2, f"Section '## {header}' missing"
    after = parts[1]
    nxt = re.search(r"\n## ", after)
    return after[: nxt.start()] if nxt else after


# ---------------------------------------------------------------------------
# 1. LCA gating: construction co-occurrence
# ---------------------------------------------------------------------------


def test_lca_with_building_context_is_classified_as_lca():
    item = _item(
        title="Embodied carbon of low-carbon construction materials in buildings",
        summary="A life cycle assessment for concrete and steel building materials.",
    )
    classified = classify_item(item, _keywords())
    assert "embodied_carbon" in classified.topics


def test_building_embodied_carbon_is_kept():
    item = _item(
        title="Embodied carbon assessment of a residential building",
        summary="LCA of the building's structural materials including steel and concrete.",
    )
    classified = classify_item(item, _keywords())
    assert "embodied_carbon" in classified.topics


def test_steel_lca_is_kept():
    item = _item(
        title="Life cycle assessment of structural steel in bridges",
        summary="EPD-based LCA of welded steel members in infrastructure.",
    )
    classified = classify_item(item, _keywords())
    assert "embodied_carbon" in classified.topics


def test_palm_biodiesel_lca_is_excluded_from_lca_topic():
    item = _item(
        title="Sustainable palm biodiesel: an LCA review",
        summary="Life cycle assessment of palm oil biofuel production.",
    )
    classified = classify_item(item, _keywords())
    assert "embodied_carbon" not in classified.topics


def test_coffee_packaging_lca_is_excluded():
    item = _item(
        title="From multimaterial to monomaterial: an LCA of flexible coffee packaging",
        summary="Carbon footprint analysis of coffee packaging materials.",
    )
    classified = classify_item(item, _keywords())
    assert "embodied_carbon" not in classified.topics


def test_passenger_transport_lca_is_excluded():
    item = _item(
        title="Beyond operational emissions: LCA of passenger transport modes",
        summary="Carbon footprint of aviation and rail passenger transport.",
    )
    classified = classify_item(item, _keywords())
    assert "embodied_carbon" not in classified.topics


def test_food_lca_is_excluded():
    item = _item(
        title="Life cycle assessment of food sovereignty in livestock crops",
        summary="Embodied carbon of food production systems.",
    )
    classified = classify_item(item, _keywords())
    assert "embodied_carbon" not in classified.topics


def test_food_lca_falls_below_minimum_score_after_penalty():
    """With negative-keyword penalty, food/biofuel LCA must drop below 5."""
    rules = _scoring_rules()
    min_score = int(rules.get("minimum_score", 5))
    item = _item(
        title="LCA of palm biodiesel and coffee packaging",
        summary="Life cycle assessment of biofuel fuel processes and food packaging.",
    )
    scored = score_item(item, _keywords(), rules)
    assert scored.score < min_score, (
        f"expected score < {min_score}, got {scored.score}; "
        f"penalty should have eliminated this LCA item"
    )


def test_construction_lca_is_not_penalized():
    """Construction LCA must not be hit by negative penalties."""
    item = _item(
        title="Embodied carbon of structural steel buildings",
        summary="LCA of construction materials for low-carbon building design.",
    )
    scored = score_item(item, _keywords(), _scoring_rules())
    assert scored.score > 0
    assert "embodied_carbon" in scored.topics


def test_off_topic_lca_does_not_receive_topic_match_bonus():
    """Off-topic LCA gets raw keyword points but no topic-match weight."""
    off = _item(
        title="LCA of palm biodiesel and fuel processes",
        summary="A life cycle assessment of biofuels.",
    )
    on = _item(
        title="LCA of structural steel buildings",
        summary="Embodied carbon of construction materials.",
    )
    off_scored = score_item(off, _keywords(), _scoring_rules())
    on_scored = score_item(on, _keywords(), _scoring_rules())
    assert on_scored.score > off_scored.score
    assert "embodied_carbon" not in off_scored.topics
    assert "embodied_carbon" in on_scored.topics


# ---------------------------------------------------------------------------
# 2. Steel construction recall
# ---------------------------------------------------------------------------


def _is_steel_topic(item: StandardItem) -> bool:
    return any(t in (item.topics or []) for t in ("structural_steel", "steel_construction"))


def _appears_in_steel_or_must_read(md: str, title: str) -> bool:
    """Strong steel items may land in 'Must Read' (score>=80) before
    'Steel Construction' due to priority routing. Either is acceptable."""
    return (
        title in _section_text(md, "Steel Construction")
        or title in _section_text(md, "Must Read")
    )


def test_steel_connection_routes_to_steel_section():
    item = _item(
        title="Bolted steel connection in a frame",
        summary="Experimental study on a welded connection design.",
    )
    classified = classify_item(item, _keywords())
    scored = score_item(classified, _keywords(), _scoring_rules())
    assert _is_steel_topic(scored)
    md = generate_markdown_briefing([scored])
    assert _appears_in_steel_or_must_read(md, item.title)


def test_steel_frame_routes_to_steel_section():
    item = _item(
        title="Modular steel frame for residential buildings",
        summary="A cold-formed steel frame system design.",
    )
    classified = classify_item(item, _keywords())
    scored = score_item(classified, _keywords(), _scoring_rules())
    assert _is_steel_topic(scored)
    md = generate_markdown_briefing([scored])
    assert _appears_in_steel_or_must_read(md, item.title)


def test_steel_concrete_composite_routes_to_steel_section():
    item = _item(
        title="Composite beam for floors",
        summary="A steel-concrete composite beam under cyclic loading.",
    )
    classified = classify_item(item, _keywords())
    scored = score_item(classified, _keywords(), _scoring_rules())
    assert _is_steel_topic(scored)
    md = generate_markdown_briefing([scored])
    assert _appears_in_steel_or_must_read(md, item.title)


def test_generic_steel_metallurgy_does_not_get_steel_topic():
    """A pure metallurgy / manufacturing paper should not be tagged steel topics."""
    item = _item(
        title="Microstructure evolution in steel during alloy casting",
        summary="Metallurgical study of phase transformation in alloy steel.",
    )
    classified = classify_item(item, _keywords())
    assert "structural_steel" not in classified.topics
    assert "steel_construction" not in classified.topics


# ---------------------------------------------------------------------------
# 3. Full-text candidate eligibility
# ---------------------------------------------------------------------------


def test_full_text_candidates_require_score_80():
    high = StandardItem(
        title="High", source="arxiv", item_type="preprint",
        score=85, metadata={"source_type": "preprint"},
    )
    mid = StandardItem(
        title="Mid", source="arxiv", item_type="preprint",
        score=79, metadata={"source_type": "preprint"},
    )
    candidates = select_candidates([high, mid], max_items=5)
    titles = [c.title for c in candidates]
    assert "High" in titles
    assert "Mid" not in titles


def test_off_topic_lca_never_reaches_full_text_threshold():
    """An off-topic LCA item with the real config should not hit score >= 80."""
    item = _item(
        title="Life cycle assessment of palm biodiesel and food packaging",
        summary="LCA review of biofuel and food fuel processes; carbon footprint.",
    )
    scored = score_item(item, _keywords(), _scoring_rules())
    assert scored.score < 80
    assert "embodied_carbon" not in scored.topics


def test_strong_steel_item_can_be_full_text_candidate():
    """A heavy steel construction item should be eligible if scored high enough."""
    # Construct a strong item and verify the candidate filter accepts it
    # at the boundary (score >= 80).
    item = StandardItem(
        title="Steel connection design in steel construction",
        source="arxiv",
        item_type="preprint",
        score=85,
        metadata={"source_type": "preprint"},
    )
    candidates = select_candidates([item], max_items=5)
    assert candidates and candidates[0].title == item.title
