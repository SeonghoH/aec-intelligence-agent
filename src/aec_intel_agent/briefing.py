"""Korean Markdown briefing generation aligned with user workflows."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from aec_intel_agent.models import StandardItem

MUST_READ_THRESHOLD = 10
SAVE_THRESHOLD = 5
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
_STEEL_KEYWORDS_IN_TEXT = ("steel", "강구조", "강재", "철골")

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _why_it_matters(item: StandardItem) -> str:
    topics = set(item.topics or [])
    phrases: list[str] = []

    if topics & _STEEL_TOPICS:
        phrases.append("강구조 / constructsteel 작업 직결")
    if topics & _LCA_TOPICS:
        phrases.append("LCA WG 관련")
    if "digital_twin" in topics:
        phrases.append("디지털 트윈 · 모니터링 연구")
    if topics & {"bim", "openbim"}:
        phrases.append("BIM · openBIM 연구 자료")
    if "ai_in_construction" in topics:
        phrases.append("AI 건설 자동화 연구")
    if topics & {"digital_architecture", "construction_technology"}:
        phrases.append("디지털 건설 기술 참고")

    if not phrases:
        return "박사 연구 참고 자료"

    # Deduplicate while preserving order, then cap at 2 phrases.
    seen: set[str] = set()
    unique: list[str] = []
    for p in phrases:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return " · ".join(unique[:2])


def _build_summary(item: StandardItem) -> str:
    text = (item.summary or "").strip()
    if not text:
        return item.title.strip()

    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]
    if not sentences:
        return item.title.strip()

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

    # Pick top 2 by hit count, tie-break by earlier position.
    top = sorted(scored, key=lambda t: (-t[0], t[1]))[:2]
    # Render in original order.
    chosen = [s for _, _, s in sorted(top, key=lambda t: t[1])]

    summary = " ".join(chosen)
    if len(summary) > SUMMARY_MAX_CHARS:
        summary = summary[: SUMMARY_MAX_CHARS - 1].rstrip() + "…"
    return summary


def _route_item(item: StandardItem) -> str:
    """Return the section key this item belongs to."""
    if item.score >= MUST_READ_THRESHOLD:
        return "must_read"

    topics = set(item.topics or [])

    if topics & _STEEL_TOPICS:
        return "steel"

    if "digital_twin" in topics:
        text = f"{item.title} {item.summary}".lower()
        if any(kw in text for kw in _STEEL_KEYWORDS_IN_TEXT):
            return "steel"

    if topics & _LCA_TOPICS:
        return "lca"

    if topics & _BIM_TOPICS:
        return "bim"

    if item.score >= SAVE_THRESHOLD:
        return "phd"

    return "weak"


def _item_card(index: int, item: StandardItem) -> str:
    title = item.title.strip() or "(제목 없음)"
    link = f"[{title}]({item.url})" if item.url else title

    rows = [
        ("출처", item.source or "-"),
        ("발행일", item.display_date),
        ("점수", str(item.score)),
        ("태그", ", ".join(item.topics) if item.topics else "-"),
        ("저자", ", ".join(item.authors[:3]) if item.authors else "-"),
        ("DOI", item.doi or "-"),
    ]
    table_lines = ["| 항목 | 내용 |", "|------|------|"]
    for label, value in rows:
        table_lines.append(f"| {label} | {value} |")

    summary = _build_summary(item)
    why = _why_it_matters(item)

    lines = [
        f"### {index}. {link}",
        "",
        f"**📌 왜 중요한가:** {why}",
        "",
        *table_lines,
        "",
        f"**요약:** {summary}",
        "",
    ]
    return "\n".join(lines)


def _render_section(title: str, subtitle: str, items: list[StandardItem]) -> str:
    header = f"## {title}\n\n> {subtitle}\n\n"
    if not items:
        return header + "*(해당 항목 없음)*\n\n"
    cards = [_item_card(i + 1, item) for i, item in enumerate(items)]
    return header + "\n".join(cards)


def generate_markdown_briefing(
    items: list[StandardItem],
    generated_at: datetime | None = None,
) -> str:
    timestamp = generated_at or datetime.now()
    date_str = timestamp.strftime("%Y-%m-%d")
    time_str = timestamp.strftime("%H:%M")

    buckets: dict[str, list[StandardItem]] = {
        "must_read": [],
        "steel": [],
        "lca": [],
        "bim": [],
        "phd": [],
        "weak": [],
    }

    for item in items:
        buckets[_route_item(item)].append(item)

    overview = (
        f"총 {len(items)}건 · "
        f"핵심 {len(buckets['must_read'])}건 · "
        f"강구조 {len(buckets['steel'])}건 · "
        f"LCA {len(buckets['lca'])}건 · "
        f"BIM {len(buckets['bim'])}건"
    )

    header = "\n".join(
        [
            "# AEC 인텔리전스 브리핑",
            "",
            f"**생성일:** {date_str} {time_str}  ",
            f"**수집 논문 수:** {len(items)}건  ",
            f"**개요:** {overview}",
            "",
            "---",
            "",
        ]
    )

    body = "\n".join(
        [
            _render_section(
                "🌟 오늘의 핵심",
                "점수가 높아 우선 읽어볼 논문",
                buckets["must_read"],
            ),
            _render_section(
                "🏗️ 강구조 & 모니터링",
                "constructsteel 작업 및 강구조 모니터링 관련",
                buckets["steel"],
            ),
            _render_section(
                "♻️ LCA · 임베디드 카본",
                "LCA WG 작업 및 탄소 평가 관련",
                buckets["lca"],
            ),
            _render_section(
                "🏛️ BIM · 디지털 트윈 · AI 자동화",
                "BIM / 디지털 트윈 / AI 자동화 연구 자료",
                buckets["bim"],
            ),
            _render_section(
                "📚 박사 연구용 참고",
                "점수 5 이상이나 위 주제에 속하지 않는 자료",
                buckets["phd"],
            ),
            _render_section(
                "🔍 약한 신호",
                "낮은 점수 / 변두리 신호 — 참고용",
                buckets["weak"],
            ),
        ]
    )

    footer = "\n---\n\n_브리핑 생성: aec-intelligence-agent_\n"

    return header + body + footer


def write_markdown_briefing(
    items: list[StandardItem],
    output_dir: Path | str = "outputs",
    filename: str | None = None,
) -> Path:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    filename = filename or f"{now.strftime('%Y-%m-%d')}_daily_briefing.md"
    briefing_path = output_path / filename
    briefing_path.write_text(
        generate_markdown_briefing(items, generated_at=now),
        encoding="utf-8",
    )
    return briefing_path
