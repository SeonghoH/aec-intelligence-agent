"""Tests for the Markdown briefing generator."""

from __future__ import annotations

import re
from datetime import datetime

from aec_intel_agent.briefing import (
    _build_summary,
    _relevance_to_seongho,
    _why_it_matters,
    generate_markdown_briefing,
)
from aec_intel_agent.models import StandardItem


def _item(**kwargs) -> StandardItem:
    defaults = {"title": "Test Paper", "source": "test"}
    return StandardItem(**{**defaults, **kwargs})


def _section_text(md: str, header: str) -> str:
    """Extract text between a level-2 header and the next level-2 header."""
    parts = md.split(f"## {header}")
    assert len(parts) >= 2, f"Section '## {header}' not found"
    after = parts[1]
    next_h2 = re.search(r"\n## ", after)
    return after[: next_h2.start()] if next_h2 else after


# --- Top-level structure -----------------------------------------------------


def test_briefing_has_title_and_date_header():
    md = generate_markdown_briefing([], generated_at=datetime(2026, 5, 16, 9, 0))
    assert "# Daily AEC / BIM / Steel Intelligence Briefing" in md
    assert "Date: 2026-05-16" in md


def test_briefing_contains_all_required_section_headers():
    md = generate_markdown_briefing([])
    for header in [
        "Executive Summary",
        "Must Read",
        "BIM / Digital Construction",
        "Steel Construction",
        "LCA / Sustainability",
        "Papers to Save",
        "Weak Signals",
        "Excluded / Low Relevance Summary",
    ]:
        assert f"## {header}" in md, f"missing section: {header}"


def test_executive_summary_lists_counts_themes_and_strength():
    items = [
        _item(title="A", score=6, topics=["bim"]),
        _item(title="B", score=6, topics=["structural_steel"]),
    ]
    md = generate_markdown_briefing(items, total_collected=10)
    es = _section_text(md, "Executive Summary")

    assert "수집 항목 수: 10건" in es
    assert "포함 항목 수: 2건" in es
    assert "주요 주제:" in es
    assert "오늘 결과 평가:" in es


def test_excluded_summary_shows_count_and_reason():
    items = [_item(score=6, topics=["bim"])]
    md = generate_markdown_briefing(items, total_collected=7)
    es = _section_text(md, "Excluded / Low Relevance Summary")
    assert "제외 항목: 6건" in es
    assert "사유:" in es


def test_empty_items_shows_no_items_message():
    md = generate_markdown_briefing([])
    assert "해당 항목 없음." in md


# --- Routing ----------------------------------------------------------------


def test_must_read_uses_threshold_of_10():
    high = _item(title="High", score=10, topics=["bim"])
    just_below = _item(title="Below", score=9, topics=["bim"])
    md = generate_markdown_briefing([high, just_below])

    must_read = _section_text(md, "Must Read")
    assert "High" in must_read
    assert "Below" not in must_read


def test_steel_topic_routes_to_steel_section():
    item = _item(title="Steel paper", score=6, topics=["structural_steel"])
    md = generate_markdown_briefing([item])
    assert "Steel paper" in _section_text(md, "Steel Construction")


def test_bim_topic_routes_to_bim_section():
    item = _item(title="IFC paper", score=6, topics=["openbim"])
    md = generate_markdown_briefing([item])
    assert "IFC paper" in _section_text(md, "BIM / Digital Construction")


def test_lca_topic_routes_to_lca_section():
    item = _item(title="LCA paper", score=6, topics=["embodied_carbon"])
    md = generate_markdown_briefing([item])
    assert "LCA paper" in _section_text(md, "LCA / Sustainability")


def test_steel_priority_beats_bim_when_both_topics_present():
    item = _item(title="Steel+BIM paper", score=6, topics=["structural_steel", "bim"])
    md = generate_markdown_briefing([item])
    assert "Steel+BIM paper" in _section_text(md, "Steel Construction")
    assert "Steel+BIM paper" not in _section_text(md, "BIM / Digital Construction")


def test_unmatched_mid_score_item_goes_to_papers_to_save():
    item = _item(title="Niche", score=6, topics=[])
    md = generate_markdown_briefing([item])
    assert "Niche" in _section_text(md, "Papers to Save")


def test_unmatched_low_score_item_goes_to_weak_signals():
    item = _item(title="Edge", score=2, topics=[])
    md = generate_markdown_briefing([item])
    assert "Edge" in _section_text(md, "Weak Signals")


def test_each_item_appears_in_exactly_one_section():
    items = [
        _item(title="Paper A", score=10, topics=["bim"], summary="alpha."),
        _item(title="Paper B", score=7, topics=["structural_steel"], summary="beta."),
        _item(title="Paper C", score=3, topics=["bim"], summary="gamma."),
    ]
    md = generate_markdown_briefing(items)

    assert len(re.findall(r"^### Paper A$", md, re.MULTILINE)) == 1
    assert len(re.findall(r"^### Paper B$", md, re.MULTILINE)) == 1
    assert len(re.findall(r"^### Paper C$", md, re.MULTILINE)) == 1


# --- Item format ------------------------------------------------------------


def test_item_block_renders_all_required_fields():
    item = _item(
        title="Card",
        url="https://example.com/x",
        score=12,
        topics=["structural_steel"],
        authors=["Alice"],
        doi="10.1/x",
        summary="A steel paper.",
        item_type="paper",
    )
    md = generate_markdown_briefing([item])

    for field in [
        "- Source:",
        "- Published:",
        "- Type:",
        "- Score:",
        "- Tags:",
        "- Summary:",
        "- Why it matters:",
        "- Relevance to Seongho:",
        "- URL:",
    ]:
        assert field in md, f"missing field: {field}"


def test_url_rendered_on_its_own_line():
    item = _item(title="X", url="https://example.com/paper", score=5, topics=["bim"])
    md = generate_markdown_briefing([item])
    assert "- URL: https://example.com/paper" in md


# --- Summary ----------------------------------------------------------------


def test_summary_picks_sentences_with_matched_keywords():
    item = _item(
        title="Some Paper",
        summary=(
            "This is an unrelated sentence about cats. "
            "We propose a BIM-based pipeline for steel construction. "
            "Future work involves further validation. "
            "BIM models are essential for openBIM workflows."
        ),
        metadata={"matched_keywords": ["BIM"]},
    )
    summary = _build_summary(item)
    assert "BIM-based pipeline" in summary
    assert "openBIM workflows" in summary
    assert "cats" not in summary


def test_summary_falls_back_to_korean_message_when_abstract_missing():
    item = _item(title="No abstract", summary="")
    assert (
        _build_summary(item)
        == "초록 또는 상세 설명이 부족하여 제목과 메타데이터 기준으로만 판단함."
    )


def test_summary_falls_back_to_korean_message_when_summary_is_whitespace():
    item = _item(title="Whitespace", summary="   \n  ")
    assert "초록 또는 상세 설명이 부족하여" in _build_summary(item)


def test_summary_preserves_original_sentence_order():
    item = _item(
        summary="Sentence A about BIM. Sentence B about BIM. Sentence C unrelated.",
        metadata={"matched_keywords": ["BIM"]},
    )
    summary = _build_summary(item)
    assert summary.index("Sentence A") < summary.index("Sentence B")


# --- Why it matters & Relevance to Seongho ---------------------------------


def test_why_it_matters_steel_phrase():
    assert "constructsteel" in _why_it_matters(_item(topics=["structural_steel"]))


def test_why_it_matters_lca_phrase():
    assert "LCA WG" in _why_it_matters(_item(topics=["embodied_carbon"]))


def test_why_it_matters_bim_phrase():
    assert "BIM-Digital Twin" in _why_it_matters(_item(topics=["bim"]))


def test_why_it_matters_ai_phrase():
    assert "건설 자동화" in _why_it_matters(_item(topics=["ai_in_construction"]))


def test_why_it_matters_default_for_no_topics():
    result = _why_it_matters(_item(topics=[]))
    assert result and "현재 주요 토픽" in result


def test_why_it_matters_caps_at_two_phrases():
    item = _item(topics=["structural_steel", "embodied_carbon", "bim", "ai_in_construction"])
    result = _why_it_matters(item)
    # At most 2 phrases joined, each ending with `.`.
    assert result.count(".") <= 2


def test_relevance_to_seongho_steel():
    assert "constructsteel" in _relevance_to_seongho(_item(topics=["structural_steel"]))


def test_relevance_to_seongho_lca():
    assert "LCA WG" in _relevance_to_seongho(_item(topics=["embodied_carbon"]))


def test_relevance_to_seongho_default():
    assert _relevance_to_seongho(_item(topics=[])).startswith("현재 우선 순위는 낮음")


# --- Strength label ---------------------------------------------------------


def test_strength_label_strong_when_many_items():
    items = [_item(score=6, topics=["bim"]) for _ in range(20)]
    md = generate_markdown_briefing(items)
    assert "강함 (Strong)" in _section_text(md, "Executive Summary")


def test_strength_label_weak_when_few_items():
    md = generate_markdown_briefing([_item(score=6, topics=["bim"])])
    assert "약함 (Weak)" in _section_text(md, "Executive Summary")
