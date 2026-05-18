"""Optional LLM-based detailed summarization for high-relevance papers.

This module reads previously extracted open-access full text and asks an
LLM (default: Gemini via google-genai) for a structured Korean summary
focused on Seongho's workflows: BIM / digital construction, structural
steel, embodied carbon / LCA, and PhD research direction.

Strict guardrails:

- Entirely optional. Disabled by default. Activated only when
  `LLM_ENABLED=true` AND a provider-specific API key is set.
- Capped at `LLM_MAX_ITEMS` runs per pipeline invocation (default 1).
- Only summarizes items with `score >= LLM_MIN_SCORE`, full-text
  successfully extracted, and a paper/preprint source type.
- Reads at most `LLM_MAX_CHARS` characters of the extracted text.
- All network errors, parse errors, and missing keys are caught and
  translated into `Failed` / `Skipped - …` statuses. The summarizer
  never raises into the main pipeline.
- Does NOT log paper text, keys, or any user-identifying value.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from aec_intel_agent.full_text import STATUS_FULL_TEXT_EXTRACTED
from aec_intel_agent.models import StandardItem

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Status / read-priority vocabulary (matches Notion select options).
# ---------------------------------------------------------------------------

STATUS_SUMMARIZED = "Summarized"
STATUS_FAILED = "Failed"
STATUS_SKIPPED_NO_FULL_TEXT = "Skipped - No Full Text"
STATUS_SKIPPED_LOW_SCORE = "Skipped - Low Score"
STATUS_NOT_ATTEMPTED = "Not Attempted"

ALL_STATUSES = (
    STATUS_SUMMARIZED,
    STATUS_FAILED,
    STATUS_SKIPPED_NO_FULL_TEXT,
    STATUS_SKIPPED_LOW_SCORE,
    STATUS_NOT_ATTEMPTED,
)

READ_PRIORITY_HIGH = "High"
READ_PRIORITY_MEDIUM = "Medium"
READ_PRIORITY_LOW = "Low"
READ_PRIORITIES = (READ_PRIORITY_HIGH, READ_PRIORITY_MEDIUM, READ_PRIORITY_LOW)

# ---------------------------------------------------------------------------
# Config from environment
# ---------------------------------------------------------------------------

DEFAULT_PROVIDER = "gemini"
DEFAULT_MODEL = "gemini-2.5-pro"
DEFAULT_MAX_ITEMS = 1
DEFAULT_MIN_SCORE = 80
DEFAULT_MAX_CHARS = 40000

CANDIDATE_SOURCE_TYPES = {"paper", "preprint"}


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        v = int(raw)
        return v if v > 0 else default
    except (ValueError, TypeError):
        return default


def is_enabled() -> bool:
    return _truthy(os.environ.get("LLM_ENABLED"))


def get_provider() -> str:
    return (os.environ.get("LLM_PROVIDER") or DEFAULT_PROVIDER).strip().lower()


def get_model() -> str:
    return (os.environ.get("LLM_MODEL") or DEFAULT_MODEL).strip()


def get_max_items() -> int:
    return _int_env("LLM_MAX_ITEMS", DEFAULT_MAX_ITEMS)


def get_min_score() -> int:
    return _int_env("LLM_MIN_SCORE", DEFAULT_MIN_SCORE)


def get_max_chars() -> int:
    return _int_env("LLM_MAX_CHARS", DEFAULT_MAX_CHARS)


def _provider_api_key(provider: str) -> str | None:
    if provider == "gemini":
        return os.environ.get("GEMINI_API_KEY")
    if provider == "openai":
        return os.environ.get("OPENAI_API_KEY")
    if provider == "anthropic":
        return os.environ.get("ANTHROPIC_API_KEY")
    return None


# ---------------------------------------------------------------------------
# Structured summary type
# ---------------------------------------------------------------------------


@dataclass
class LLMSummary:
    summary_status: str = STATUS_NOT_ATTEMPTED
    detailed_summary: str = ""
    research_question: str = ""
    methodology: str = ""
    key_findings: str = ""
    limitations: str = ""
    practical_value: str = ""
    relevance_to_phd: str = ""
    relevance_to_constructsteel: str = ""
    relevance_to_lca_wg: str = ""
    read_priority: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Candidate selection
# ---------------------------------------------------------------------------


def _source_type(item: StandardItem) -> str:
    meta = item.metadata if isinstance(item.metadata, dict) else {}
    return str(meta.get("source_type") or item.item_type or "").lower()


def select_candidates(
    items: list[StandardItem],
    *,
    min_score: int | None = None,
    max_items: int | None = None,
) -> list[StandardItem]:
    """Select items eligible for LLM summarization.

    Eligibility (all must hold):
    - ``score >= min_score`` (default `LLM_MIN_SCORE`, fallback 80)
    - ``full_text_status == "Full Text Extracted"``
    - ``full_text_path`` exists on disk
    - ``source_type`` is `paper` or `preprint`
    """
    min_s = min_score if min_score is not None else get_min_score()
    limit = max_items if max_items is not None else get_max_items()
    if limit <= 0:
        return []

    out: list[StandardItem] = []
    for item in items:
        if item.score < min_s:
            continue
        if item.full_text_status != STATUS_FULL_TEXT_EXTRACTED:
            continue
        path = item.full_text_path
        if not path or not Path(path).exists():
            continue
        if _source_type(item) not in CANDIDATE_SOURCE_TYPES:
            continue
        out.append(item)
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


_PROMPT_TEMPLATE = """\
당신은 건설/AEC 분야 연구 보조 에이전트입니다. 사용자(Seongho HA)는
다음 영역에서 일합니다:

- BIM, openBIM, IFC, 디지털 건설, 디지털 트윈
- 강구조 / constructsteel (산업 모니터링)
- 박사 연구: BIM·디지털 트윈·AI 기반 건설 자동화
- LCA WG (embodied carbon, 건설 LCA)

아래 논문 전문을 읽고, 한국어로 정확하고 간결한 구조화 요약을 작성하세요.

엄격한 규칙:
1) 사실을 지어내지 마세요. 논문에 없는 내용은 "정보 없음"으로 표시.
2) 논문이 직접 주장한 내용과, 사용자 업무에 대한 추론된 적합성을 분리하세요.
3) 각 필드는 1~4문장으로 간결하게.
4) "정보 없음"이라고 쓰는 것을 두려워하지 마세요.
5) 출력은 반드시 아래 JSON 형식만 사용하세요. 추가 설명/마크다운 없음.

JSON 스키마:
{{
  "detailed_summary": "논문 전체를 한 문단(3~5문장)으로 요약",
  "research_question": "논문이 답하려는 핵심 질문",
  "methodology": "사용된 방법, 데이터, 실험 설계",
  "key_findings": "주요 발견 사항 (정량 결과 우선)",
  "limitations": "저자가 명시한 한계 또는 명백한 한계",
  "practical_value": "실무에 어떻게 활용 가능한가",
  "relevance_to_phd": "BIM/디지털 트윈/AI 건설 자동화 박사 연구와의 관련성",
  "relevance_to_constructsteel": "강구조/산업 모니터링 업무와의 관련성",
  "relevance_to_lca_wg": "embodied carbon / 건설 LCA 워킹그룹과의 관련성",
  "read_priority": "High / Medium / Low 중 하나"
}}

논문 메타데이터:
- 제목: {title}
- 출처: {source}
- 점수: {score}
- 태그: {topics}

논문 본문 (최대 {max_chars}자):
---
{text}
---

JSON만 출력하세요:"""


def build_prompt(item: StandardItem, text: str, max_chars: int) -> str:
    truncated = text[:max_chars]
    return _PROMPT_TEMPLATE.format(
        title=(item.title or "")[:300],
        source=item.source or "",
        score=item.score,
        topics=", ".join(item.topics or []) or "(없음)",
        max_chars=max_chars,
        text=truncated,
    )


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)
_REQUIRED_FIELDS = (
    "detailed_summary",
    "research_question",
    "methodology",
    "key_findings",
    "limitations",
    "practical_value",
    "relevance_to_phd",
    "relevance_to_constructsteel",
    "relevance_to_lca_wg",
    "read_priority",
)


def parse_response(text: str) -> LLMSummary:
    """Parse the model output into a `LLMSummary`. Raises ValueError on failure."""
    if not text:
        raise ValueError("empty LLM response")

    # Strip code-fence wrappers like ```json ... ``` if present.
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.DOTALL)

    match = _JSON_BLOCK.search(cleaned)
    if not match:
        raise ValueError("no JSON object in LLM response")

    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("LLM response did not parse to an object")

    def _get(name: str) -> str:
        val = data.get(name, "")
        if isinstance(val, list):
            val = " ".join(str(x) for x in val)
        return str(val or "").strip()

    priority = _get("read_priority").title()
    if priority not in READ_PRIORITIES:
        priority = READ_PRIORITY_MEDIUM

    return LLMSummary(
        summary_status=STATUS_SUMMARIZED,
        detailed_summary=_get("detailed_summary"),
        research_question=_get("research_question"),
        methodology=_get("methodology"),
        key_findings=_get("key_findings"),
        limitations=_get("limitations"),
        practical_value=_get("practical_value"),
        relevance_to_phd=_get("relevance_to_phd"),
        relevance_to_constructsteel=_get("relevance_to_constructsteel"),
        relevance_to_lca_wg=_get("relevance_to_lca_wg"),
        read_priority=priority,
    )


# ---------------------------------------------------------------------------
# Provider calls
# ---------------------------------------------------------------------------


def _call_gemini(prompt: str, *, api_key: str, model: str) -> str:
    """Call Google Gemini via the official google-genai client."""
    from google import genai

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=prompt,
    )
    return getattr(response, "text", "") or ""


def call_llm(prompt: str, *, provider: str, model: str, api_key: str) -> str:
    """Dispatch the LLM call by provider. Returns raw response text."""
    if provider == "gemini":
        return _call_gemini(prompt, api_key=api_key, model=model)
    raise NotImplementedError(f"LLM provider {provider!r} not supported")


# ---------------------------------------------------------------------------
# Item-level processing
# ---------------------------------------------------------------------------


def _read_full_text(path: str, max_chars: int) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")[:max_chars]
    except Exception as exc:
        logger.warning("LLM: could not read full text at %s: %s", path, exc)
        return ""


def summarize_item(
    item: StandardItem,
    *,
    provider: str,
    model: str,
    api_key: str,
    max_chars: int | None = None,
) -> LLMSummary:
    """Summarize a single item. Never raises — returns Failed on errors."""
    limit = max_chars if max_chars is not None else get_max_chars()

    text = _read_full_text(item.full_text_path or "", limit)
    if not text.strip():
        return LLMSummary(summary_status=STATUS_FAILED)

    prompt = build_prompt(item, text, limit)
    try:
        raw = call_llm(prompt, provider=provider, model=model, api_key=api_key)
    except Exception as exc:
        logger.warning("LLM: provider call failed (%s): %s", provider, exc)
        return LLMSummary(summary_status=STATUS_FAILED)

    try:
        return parse_response(raw)
    except Exception as exc:
        logger.warning("LLM: response parse failed: %s", exc)
        return LLMSummary(summary_status=STATUS_FAILED)


# ---------------------------------------------------------------------------
# Pipeline entry point
# ---------------------------------------------------------------------------


def _attach_summary(item: StandardItem, summary: LLMSummary) -> StandardItem:
    """Attach the summary fields to item.metadata under a dedicated key."""
    meta = dict(item.metadata) if isinstance(item.metadata, dict) else {}
    meta["llm_summary"] = summary.to_dict()
    if hasattr(item, "model_copy"):
        return item.model_copy(update={"metadata": meta})
    return item.copy(update={"metadata": meta})


def process_items(items: list[StandardItem]) -> list[StandardItem]:
    """Run LLM summarization for eligible items.

    Never raises. Items are returned with a new `metadata["llm_summary"]`
    dict if processed; untouched otherwise. Skips the entire step when:
    - `LLM_ENABLED` is not truthy
    - the provider's API key is missing
    """
    if not is_enabled():
        logger.info("LLM: disabled via LLM_ENABLED — skipping summarization.")
        return items

    provider = get_provider()
    api_key = _provider_api_key(provider)
    if not api_key:
        logger.info(
            "LLM: API key for provider %r missing — skipping summarization.",
            provider,
        )
        return items

    candidates = select_candidates(items)
    if not candidates:
        logger.info("LLM: 0 eligible candidates (score≥%d + full-text).", get_min_score())
        return items

    model = get_model()
    logger.info(
        "LLM: summarizing %d candidate(s) with provider=%s, model=%s.",
        len(candidates), provider, model,
    )

    candidate_ids = {id(c) for c in candidates}
    out: list[StandardItem] = []
    for item in items:
        if id(item) in candidate_ids:
            try:
                summary = summarize_item(
                    item, provider=provider, model=model, api_key=api_key
                )
            except Exception as exc:  # last-resort safety net
                logger.warning("LLM: unexpected failure: %s", exc)
                summary = LLMSummary(summary_status=STATUS_FAILED)
            out.append(_attach_summary(item, summary))
        else:
            out.append(item)
    return out
