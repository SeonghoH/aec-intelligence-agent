"""Tests for the optional LLM summarization module.

All tests run with NO real LLM calls — `call_llm` is monkeypatched. Network
clients (Gemini / OpenAI / Anthropic) are never imported or instantiated.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from aec_intel_agent import llm_summarizer as llm
from aec_intel_agent.full_text import STATUS_FULL_TEXT_EXTRACTED
from aec_intel_agent.models import StandardItem


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _full_text_item(tmp_path: Path, **overrides) -> StandardItem:
    text_path = tmp_path / "paper.txt"
    text_path.write_text("Full extracted paper text " * 200, encoding="utf-8")
    defaults = dict(
        title="A BIM-based framework for steel construction",
        source="arxiv",
        url="http://arxiv.org/abs/2501.99999",
        item_type="preprint",
        score=85,
        full_text_status=STATUS_FULL_TEXT_EXTRACTED,
        full_text_path=str(text_path),
        metadata={"source_type": "preprint"},
    )
    defaults.update(overrides)
    return StandardItem(**defaults)


_GOOD_JSON_RESPONSE = json.dumps({
    "detailed_summary": "BIM 기반 강구조 프레임 자동 설계 시스템 제안.",
    "research_question": "BIM 데이터로 강구조 설계를 자동화할 수 있는가?",
    "methodology": "케이스 스터디 + 알고리즘 검증.",
    "key_findings": "수동 대비 30% 시간 절감.",
    "limitations": "단일 케이스, 일반화 한계.",
    "practical_value": "강구조 EPC에 적용 가능.",
    "relevance_to_phd": "BIM·자동화 박사 연구와 매우 높은 관련성.",
    "relevance_to_constructsteel": "constructsteel 업무와 직접 연결.",
    "relevance_to_lca_wg": "LCA 직접 다루지 않음. 정보 없음.",
    "read_priority": "High",
})


# ---------------------------------------------------------------------------
# Enablement & key gating
# ---------------------------------------------------------------------------


def test_disabled_when_env_unset(tmp_path):
    item = _full_text_item(tmp_path)
    out = llm.process_items([item])
    assert out == [item]


def test_disabled_when_env_false(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_ENABLED", "false")
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    item = _full_text_item(tmp_path)
    out = llm.process_items([item])
    assert out == [item]


def test_skipped_when_api_key_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    # No GEMINI_API_KEY set.
    item = _full_text_item(tmp_path)
    out = llm.process_items([item])
    assert "llm_summary" not in (out[0].metadata or {})


# ---------------------------------------------------------------------------
# Candidate selection
# ---------------------------------------------------------------------------


def test_low_score_item_is_not_a_candidate(tmp_path):
    item = _full_text_item(tmp_path, score=50)
    assert llm.select_candidates([item], min_score=80) == []


def test_item_without_full_text_path_is_not_a_candidate(tmp_path):
    item = _full_text_item(tmp_path, full_text_path=None)
    assert llm.select_candidates([item]) == []


def test_item_with_nonexistent_full_text_path_is_not_a_candidate(tmp_path):
    item = _full_text_item(tmp_path, full_text_path="/no/such/file.txt")
    assert llm.select_candidates([item]) == []


def test_item_with_wrong_status_is_not_a_candidate(tmp_path):
    item = _full_text_item(tmp_path, full_text_status="PDF Download Failed")
    assert llm.select_candidates([item]) == []


def test_non_paper_source_type_is_not_a_candidate(tmp_path):
    item = _full_text_item(
        tmp_path, item_type="article", metadata={"source_type": "blog"}
    )
    assert llm.select_candidates([item]) == []


def test_max_items_limit_is_respected(tmp_path):
    items = []
    for i in range(5):
        sub = tmp_path / f"sub{i}"
        sub.mkdir()
        target = sub / "paper.txt"
        target.write_text("text", encoding="utf-8")
        items.append(StandardItem(
            title=f"Paper {i}",
            source="arxiv",
            url=f"http://arxiv.org/abs/2501.{i:05d}",
            item_type="preprint",
            score=90,
            full_text_status=STATUS_FULL_TEXT_EXTRACTED,
            full_text_path=str(target),
            metadata={"source_type": "preprint"},
        ))
    selected = llm.select_candidates(items, max_items=2)
    assert len(selected) == 2


# ---------------------------------------------------------------------------
# Prompt + truncation
# ---------------------------------------------------------------------------


def test_prompt_truncates_text_to_max_chars(tmp_path):
    item = _full_text_item(tmp_path)
    long_text = "X" * 50000
    prompt = llm.build_prompt(item, long_text, max_chars=1000)
    # The prompt embeds at most 1000 X's; the prompt itself is longer
    # because of the surrounding template.
    assert prompt.count("X") == 1000


def test_prompt_includes_item_metadata(tmp_path):
    item = _full_text_item(tmp_path, title="Special BIM paper")
    prompt = llm.build_prompt(item, "body", max_chars=100)
    assert "Special BIM paper" in prompt
    assert "JSON" in prompt


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def test_parse_valid_json_response_returns_structured_fields():
    summary = llm.parse_response(_GOOD_JSON_RESPONSE)
    assert summary.summary_status == llm.STATUS_SUMMARIZED
    assert summary.detailed_summary.startswith("BIM 기반")
    assert summary.read_priority == "High"


def test_parse_response_strips_code_fences():
    fenced = "```json\n" + _GOOD_JSON_RESPONSE + "\n```"
    summary = llm.parse_response(fenced)
    assert summary.summary_status == llm.STATUS_SUMMARIZED


def test_parse_response_normalizes_invalid_priority_to_medium():
    payload = json.loads(_GOOD_JSON_RESPONSE)
    payload["read_priority"] = "ULTRA"
    summary = llm.parse_response(json.dumps(payload))
    assert summary.read_priority == "Medium"


def test_parse_empty_response_raises():
    with pytest.raises(ValueError):
        llm.parse_response("")


def test_parse_garbage_response_raises():
    with pytest.raises(ValueError):
        llm.parse_response("not even close to JSON")


# ---------------------------------------------------------------------------
# Item-level summarize
# ---------------------------------------------------------------------------


def test_summarize_item_attaches_structured_summary(monkeypatch, tmp_path):
    item = _full_text_item(tmp_path)
    monkeypatch.setattr(
        "aec_intel_agent.llm_summarizer.call_llm",
        lambda prompt, provider, model, api_key: _GOOD_JSON_RESPONSE,
    )
    summary = llm.summarize_item(
        item, provider="gemini", model="gemini-2.5-pro", api_key="fake"
    )
    assert summary.summary_status == llm.STATUS_SUMMARIZED
    assert "BIM" in summary.detailed_summary


def test_summarize_item_returns_failed_on_provider_error(monkeypatch, tmp_path):
    item = _full_text_item(tmp_path)

    def boom(**_):
        raise RuntimeError("network down")

    monkeypatch.setattr("aec_intel_agent.llm_summarizer.call_llm", boom)
    summary = llm.summarize_item(
        item, provider="gemini", model="gemini-2.5-pro", api_key="fake"
    )
    assert summary.summary_status == llm.STATUS_FAILED


def test_summarize_item_returns_failed_on_parse_error(monkeypatch, tmp_path):
    item = _full_text_item(tmp_path)
    monkeypatch.setattr(
        "aec_intel_agent.llm_summarizer.call_llm",
        lambda prompt, **kw: "not valid json",
    )
    summary = llm.summarize_item(
        item, provider="gemini", model="gemini-2.5-pro", api_key="fake"
    )
    assert summary.summary_status == llm.STATUS_FAILED


# ---------------------------------------------------------------------------
# End-to-end process_items (still mocked)
# ---------------------------------------------------------------------------


def test_process_items_attaches_metadata_to_candidate(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    monkeypatch.setenv("LLM_MIN_SCORE", "80")
    monkeypatch.setenv("LLM_MAX_ITEMS", "1")
    monkeypatch.setattr(
        "aec_intel_agent.llm_summarizer.call_llm",
        lambda prompt, **kw: _GOOD_JSON_RESPONSE,
    )

    candidate = _full_text_item(tmp_path)
    bystander = _full_text_item(tmp_path, score=10, title="Low score")

    out = llm.process_items([candidate, bystander])

    assert "llm_summary" in (out[0].metadata or {})
    summary = out[0].metadata["llm_summary"]
    assert summary["summary_status"] == llm.STATUS_SUMMARIZED
    # Bystander stays untouched.
    assert "llm_summary" not in (out[1].metadata or {})


def test_process_items_no_op_when_no_candidates(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    item = _full_text_item(tmp_path, score=10)
    out = llm.process_items([item])
    assert "llm_summary" not in (out[0].metadata or {})


def test_pipeline_never_crashes_when_provider_call_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "fake")

    def boom(**_):
        raise RuntimeError("provider down")

    monkeypatch.setattr("aec_intel_agent.llm_summarizer.call_llm", boom)
    item = _full_text_item(tmp_path)
    out = llm.process_items([item])
    # Item is returned with a Failed status attached (no crash).
    summary = (out[0].metadata or {}).get("llm_summary")
    assert summary is not None
    assert summary["summary_status"] == llm.STATUS_FAILED


# ---------------------------------------------------------------------------
# Notion integration safety
# ---------------------------------------------------------------------------


def test_notion_update_failure_does_not_crash(monkeypatch, tmp_path):
    """The full pipeline must keep going even when the Notion patch fails."""
    from aec_intel_agent import notion_client

    monkeypatch.setenv("NOTION_TOKEN", "t")
    monkeypatch.setenv("NOTION_DAILY_DB_ID", "d")
    monkeypatch.setenv("NOTION_RESEARCH_DB_ID", "r")

    def boom(*a, **k):
        raise RuntimeError("notion is on fire")

    monkeypatch.setattr(notion_client, "_find_existing_research_item", boom)

    item = _full_text_item(tmp_path)
    # Should return False (handled internally), not raise.
    result = notion_client.update_research_item_summary(
        item, {"detailed_summary": "x"}
    )
    assert result is False
