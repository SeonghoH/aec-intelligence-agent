"""Tests for the Markdown briefing generator."""

from __future__ import annotations

import re
from datetime import datetime

from aec_intel_agent.briefing import (
    _build_summary,
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


def test_briefing_contains_korean_section_headers():
    items = [_item(score=12, topics=["bim"])]
    md = generate_markdown_briefing(items, generated_at=datetime(2026, 5, 16, 9, 0))

    assert "오늘의 핵심" in md
    assert "강구조 & 모니터링" in md
    assert "LCA · 임베디드 카본" in md
    assert "BIM · 디지털 트윈 · AI 자동화" in md
    assert "박사 연구용 참고" in md
    assert "약한 신호" in md


def test_must_read_threshold():
    high = _item(title="High Score", score=15, topics=["bim"])
    low = _item(title="Low Score", score=3, topics=["bim"])
    md = generate_markdown_briefing([high, low])

    must_read = _section_text(md, "🌟 오늘의 핵심")
    assert "High Score" in must_read
    assert "Low Score" not in must_read


def test_bim_topic_goes_to_bim_section():
    item = _item(title="IFC paper", score=6, topics=["openbim"])
    md = generate_markdown_briefing([item])

    bim = _section_text(md, "🏛️ BIM · 디지털 트윈 · AI 자동화")
    assert "IFC paper" in bim


def test_steel_topic_goes_to_steel_section():
    item = _item(title="Steel frame study", score=6, topics=["structural_steel"])
    md = generate_markdown_briefing([item])

    steel = _section_text(md, "🏗️ 강구조 & 모니터링")
    assert "Steel frame study" in steel


def test_lca_topic_goes_to_lca_section():
    item = _item(title="LCA of concrete vs steel", score=6, topics=["embodied_carbon"])
    md = generate_markdown_briefing([item])

    lca = _section_text(md, "♻️ LCA · 임베디드 카본")
    assert "LCA of concrete vs steel" in lca


def test_digital_twin_with_steel_mention_routes_to_steel_section():
    item = _item(
        title="Digital twin for steel bridge monitoring",
        score=6,
        topics=["digital_twin"],
        summary="A steel bridge digital twin pilot.",
    )
    md = generate_markdown_briefing([item])

    steel = _section_text(md, "🏗️ 강구조 & 모니터링")
    assert "steel bridge monitoring" in steel


def test_phd_section_collects_unmatched_mid_score_items():
    item = _item(title="Niche topic", score=6, topics=[])
    md = generate_markdown_briefing([item])

    phd = _section_text(md, "📚 박사 연구용 참고")
    assert "Niche topic" in phd


def test_each_item_appears_in_exactly_one_section():
    items = [
        _item(title="Paper A", score=12, topics=["bim"], summary="alpha."),
        _item(title="Paper B", score=7, topics=["structural_steel"], summary="beta."),
        _item(title="Paper C", score=3, topics=["bim"], summary="gamma."),
    ]
    md = generate_markdown_briefing(items)

    # Each title appears exactly once as a numbered card heading.
    assert len(re.findall(r"### \d+\. Paper A", md)) == 1
    assert len(re.findall(r"### \d+\. Paper B", md)) == 1
    assert len(re.findall(r"### \d+\. Paper C", md)) == 1


def test_url_rendered_as_markdown_link():
    item = _item(
        title="Linked Paper",
        url="https://example.com/paper",
        score=5,
        topics=["bim"],
    )
    md = generate_markdown_briefing([item])

    assert "[Linked Paper](https://example.com/paper)" in md


def test_empty_items_shows_no_items_message():
    md = generate_markdown_briefing([])
    assert "해당 항목 없음" in md
    assert "0건" in md


def test_why_it_matters_steel_phrase():
    item = _item(topics=["structural_steel"])
    assert "강구조" in _why_it_matters(item)


def test_why_it_matters_lca_phrase():
    item = _item(topics=["embodied_carbon"])
    assert "LCA WG" in _why_it_matters(item)


def test_why_it_matters_default_for_no_topics():
    item = _item(topics=[])
    assert _why_it_matters(item) == "박사 연구 참고 자료"


def test_why_it_matters_caps_at_two_phrases():
    item = _item(topics=["structural_steel", "embodied_carbon", "digital_twin", "bim"])
    result = _why_it_matters(item)
    assert result.count("·") <= 1  # at most 2 phrases joined by " · "


def test_deterministic_summary_picks_sentences_with_keywords():
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
    # The unrelated sentence should not appear.
    assert "cats" not in summary


def test_deterministic_summary_falls_back_to_title_when_empty():
    item = _item(title="Fallback Title", summary="")
    assert _build_summary(item) == "Fallback Title"


def test_deterministic_summary_preserves_original_order():
    item = _item(
        summary="Sentence A about BIM. Sentence B about BIM. Sentence C unrelated.",
        metadata={"matched_keywords": ["BIM"]},
    )
    summary = _build_summary(item)
    assert summary.index("Sentence A") < summary.index("Sentence B")


def test_item_card_renders_metadata_table_and_why():
    item = _item(
        title="Card Test",
        url="https://example.com/x",
        score=12,
        topics=["structural_steel"],
        authors=["Alice", "Bob"],
        doi="10.1/x",
        summary="A steel paper.",
    )
    md = generate_markdown_briefing([item])

    assert "| 항목 | 내용 |" in md
    assert "| 출처 | test |" in md
    assert "| 발행일 |" in md
    assert "| 점수 | 12 |" in md
    assert "| 태그 | structural_steel |" in md
    assert "**📌 왜 중요한가:**" in md
    assert "강구조" in md
    assert "**요약:**" in md


def test_overview_line_present():
    items = [
        _item(title="A", score=12, topics=["bim"]),
        _item(title="B", score=6, topics=["structural_steel"]),
        _item(title="C", score=6, topics=["embodied_carbon"]),
    ]
    md = generate_markdown_briefing(items)
    assert "개요:" in md
    assert "총 3건" in md
    assert "강구조 1건" in md
    assert "LCA 1건" in md


def test_footer_present():
    md = generate_markdown_briefing([])
    assert "브리핑 생성: aec-intelligence-agent" in md
