"""Markdown briefing generator for the AEC intelligence pipeline."""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from aec_intel_agent.models import StandardItem

# All briefing timestamps are anchored to Asia/Seoul so the date the user
# sees on their morning briefing matches their local calendar day, regardless
# of where the pipeline runs (GitHub runners default to UTC).
KST = ZoneInfo("Asia/Seoul")

MUST_READ_THRESHOLD = 80
SAVE_THRESHOLD = 30
SUMMARY_MAX_CHARS = 400

_STEEL_TOPICS = {"structural_steel", "steel_construction"}
_LCA_TOPICS = {"embodied_carbon"}
_BIM_TOPICS = {
    "bim",
    "openbim",
    "digital_architecture",
    "construction_technology",
    "digital_twin",
    "ai_in_construction",
}

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_MISSING_SUMMARY = (
    "초록 또는 상세 설명이 부족하여 제목과 메타데이터 기준으로만 판단함."
)
_DEFAULT_WHY = "현재 주요 토픽과의 직접 연결은 약함. 추후 참고용으로만 검토."
_DEFAULT_RELEVANCE = "현재 우선 순위는 낮음. 박사 연구 참고용으로만 보관."


def _route_item(item: StandardItem) -> str:
    """Route item into one section. Priority: Must Read → Steel → BIM → LCA → Save → Weak."""
    if item.score >= MUST_READ_THRESHOLD:
        return "must_read"
    topics = set(item.topics or [])
    if topics & _STEEL_TOPICS:
        return "steel"
    if topics & _BIM_TOPICS:
        return "bim"
    if topics & _LCA_TOPICS:
        return "lca"
    if item.score >= SAVE_THRESHOLD:
        return "save"
    return "weak"


def _dedup_keep_order(phrases: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for p in phrases:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _why_it_matters(item: StandardItem) -> str:
    """Topic-driven Korean rationale tying the item to user workflows."""
    topics = set(item.topics or [])
    phrases: list[str] = []
    if topics & ({"bim", "openbim", "digital_twin", "digital_architecture", "construction_technology"}):
        phrases.append(
            "BIM-Digital Twin-AI 기반 의사결정 지원 시스템과 연결될 수 있음."
        )
    if topics & _STEEL_TOPICS:
        phrases.append(
            "constructsteel의 강구조 기술 동향 및 프로젝트 발굴에 참고 가능함."
        )
    if topics & _LCA_TOPICS:
        phrases.append(
            "LCA WG 및 embodied carbon 관련 연구 방향과 연결 가능함."
        )
    if "ai_in_construction" in topics:
        phrases.append(
            "건설 자동화 및 설계 지원 에이전트 개발 방향과 연결 가능함."
        )
    if not phrases:
        return _DEFAULT_WHY
    return " ".join(_dedup_keep_order(phrases)[:2])


def _relevance_to_seongho(item: StandardItem) -> str:
    """Personalized phrasing tying topics to Seongho's concrete workstreams."""
    topics = set(item.topics or [])
    phrases: list[str] = []
    if topics & _STEEL_TOPICS:
        phrases.append("constructsteel 강구조 모니터링 업무와 직접 연결됨.")
    if topics & _LCA_TOPICS:
        phrases.append("LCA WG 작업 및 박사 연구와 직접 연결됨.")
    if topics & {"bim", "openbim"}:
        phrases.append("BIM 박사 연구의 핵심 주제와 직접 연결됨.")
    if "digital_twin" in topics:
        phrases.append("디지털 트윈 모니터링 박사 연구와 직접 연결됨.")
    if "ai_in_construction" in topics:
        phrases.append("건설 자동화 에이전트 박사 연구 방향과 일치함.")
    if not phrases:
        return _DEFAULT_RELEVANCE
    return " ".join(_dedup_keep_order(phrases)[:2])


def _build_summary(item: StandardItem) -> str:
    """Deterministic 1–2 sentence summary from abstract; Korean fallback if missing."""
    text = (item.summary or "").strip()
    if not text:
        return _MISSING_SUMMARY

    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]
    if not sentences:
        return _MISSING_SUMMARY

    matched = [
        kw.lower()
        for kw in item.metadata.get("matched_keywords", [])
        if isinstance(kw, str)
    ]

    scored: list[tuple[int, int, str]] = []
    for idx, sentence in enumerate(sentences):
        lower = sentence.lower()
        hits = sum(1 for kw in matched if kw in lower)
        scored.append((hits, idx, sentence))

    top = sorted(scored, key=lambda t: (-t[0], t[1]))[:2]
    chosen = [s for _, _, s in sorted(top, key=lambda t: t[1])]

    summary = " ".join(chosen)
    if len(summary) > SUMMARY_MAX_CHARS:
        summary = summary[: SUMMARY_MAX_CHARS - 1].rstrip() + "…"
    return summary


def _strength_label(included_count: int) -> str:
    if included_count >= 15:
        return "강함 (Strong)"
    if included_count >= 5:
        return "보통 (Moderate)"
    return "약함 (Weak)"


def _main_themes(items: list[StandardItem]) -> str:
    counter: Counter[str] = Counter()
    for item in items:
        for topic in item.topics or []:
            counter[topic] += 1
    if not counter:
        return "감지된 주요 주제 없음."
    top = [name for name, _ in counter.most_common(3)]
    return ", ".join(top)


def _item_block(item: StandardItem) -> str:
    title = (item.title or "").strip() or "(제목 없음)"
    tags = ", ".join(item.topics) if item.topics else "(없음)"
    url = item.url or "(없음)"
    source = item.source or "-"
    source_type = item.item_type or "-"
    published = item.display_date

    summary = _build_summary(item)
    why = _why_it_matters(item)
    rel = _relevance_to_seongho(item)

    return "\n".join(
        [
            f"### {title}",
            "",
            f"- Source: {source}",
            f"- Published: {published}",
            f"- Type: {source_type}",
            f"- Score: {item.score}",
            f"- Tags: {tags}",
            f"- Summary: {summary}",
            f"- Why it matters: {why}",
            f"- Relevance to Seongho: {rel}",
            f"- URL: {url}",
            "",
        ]
    )


def _section(header: str, items: list[StandardItem]) -> str:
    parts = [f"## {header}", ""]
    if not items:
        parts.append("해당 항목 없음.")
        parts.append("")
        return "\n".join(parts)
    for item in items:
        parts.append(_item_block(item))
    return "\n".join(parts)


def generate_markdown_briefing(
    items: list[StandardItem],
    generated_at: datetime | None = None,
    total_collected: int | None = None,
) -> str:
    timestamp = generated_at or datetime.now(KST)
    date_str = timestamp.strftime("%Y-%m-%d")

    if total_collected is None:
        total_collected = len(items)
    excluded = max(total_collected - len(items), 0)

    buckets: dict[str, list[StandardItem]] = {
        "must_read": [],
        "steel": [],
        "bim": [],
        "lca": [],
        "save": [],
        "weak": [],
    }
    for item in items:
        buckets[_route_item(item)].append(item)

    themes = _main_themes(items)
    strength = _strength_label(len(items))

    header = (
        "# Daily AEC / BIM / Steel Intelligence Briefing\n"
        f"Date: {date_str}\n\n"
    )

    exec_summary = "\n".join(
        [
            "## Executive Summary",
            "",
            f"- 수집 항목 수: {total_collected}건",
            f"- 포함 항목 수: {len(items)}건",
            f"- 주요 주제: {themes}",
            f"- 오늘 결과 평가: {strength}",
            "",
        ]
    )

    body = "\n".join(
        [
            _section("Must Read", buckets["must_read"]),
            _section("BIM / Digital Construction", buckets["bim"]),
            _section("Steel Construction", buckets["steel"]),
            _section("LCA / Sustainability", buckets["lca"]),
            _section("Papers to Save", buckets["save"]),
            _section("Weak Signals", buckets["weak"]),
        ]
    )

    excluded_section = "\n".join(
        [
            "## Excluded / Low Relevance Summary",
            "",
            f"- 수집 대비 제외 항목: {excluded}건",
            "- 사유: 최소 점수 미달 또는 키워드 매칭 부족.",
            "",
        ]
    )

    return header + exec_summary + body + excluded_section


def write_markdown_briefing(
    items: list[StandardItem],
    output_dir: Path | str = "outputs",
    filename: str | None = None,
    total_collected: int | None = None,
) -> Path:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    now = datetime.now(KST)
    filename = filename or f"{now.strftime('%Y-%m-%d')}_daily_briefing.md"
    briefing_path = output_path / filename
    briefing_path.write_text(
        generate_markdown_briefing(
            items, generated_at=now, total_collected=total_collected
        ),
        encoding="utf-8",
    )
    return briefing_path
