"""Tests for the optional Notion upload integration."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from aec_intel_agent import notion_client
from aec_intel_agent.models import StandardItem


def _sample_item(**overrides) -> StandardItem:
    defaults = dict(
        title="Test paper on BIM and steel",
        source="crossref",
        url="https://doi.org/10.1234/abc",
        doi="10.1234/abc",
        item_type="paper",
        published_date=date(2026, 5, 1),
        authors=["Alice"],
        summary="A study on BIM integration with steel construction monitoring.",
        topics=["bim", "structural_steel"],
        score=12,
        metadata={"source_type": "paper", "matched_keywords": ["BIM"]},
    )
    defaults.update(overrides)
    return StandardItem(**defaults)


def _set_notion_env(monkeypatch, daily="daily-db", research="research-db"):
    monkeypatch.setenv("NOTION_TOKEN", "secret-fake")
    monkeypatch.setenv("NOTION_DAILY_DB_ID", daily)
    monkeypatch.setenv("NOTION_RESEARCH_DB_ID", research)


def _make_post_recorder(*, daily_results=None, research_results=None):
    """Build a fake requests.post that returns canned query results.

    `daily_results` and `research_results` are lists of `results` arrays —
    each query for the respective DB consumes one entry. POSTs to /pages
    always succeed and return a unique id.
    """
    daily_queue = list(daily_results or [])
    research_queue = list(research_results or [])
    calls: list[dict] = []

    def fake_post(url, **kwargs):
        mock = MagicMock()
        mock.raise_for_status.return_value = None
        body = kwargs.get("json", {})
        calls.append({"url": url, "json": body})

        if url.endswith("/query"):
            db_id = url.split("/databases/")[1].split("/query")[0]
            queue = daily_queue if db_id == "daily-db" else research_queue
            results = queue.pop(0) if queue else []
            mock.json.return_value = {"results": results}
        elif url.endswith("/pages"):
            mock.json.return_value = {"id": f"page-{len(calls)}"}
        else:
            mock.json.return_value = {}
        return mock

    fake_post.calls = calls
    return fake_post


EXPECTED_EMPTY = {
    "daily_created": 0,
    "daily_skipped": 0,
    "items_uploaded": 0,
    "items_skipped": 0,
    "items_failed": 0,
}


# ---------------------------------------------------------------------------
# Config detection
# ---------------------------------------------------------------------------


def test_is_configured_false_when_any_env_missing(monkeypatch):
    monkeypatch.setenv("NOTION_DAILY_DB_ID", "d")
    monkeypatch.setenv("NOTION_RESEARCH_DB_ID", "r")
    assert notion_client.is_configured() is False


def test_is_configured_true_when_all_set(monkeypatch):
    _set_notion_env(monkeypatch)
    assert notion_client.is_configured() is True


# ---------------------------------------------------------------------------
# Skip behavior
# ---------------------------------------------------------------------------


def test_upload_skips_when_env_missing_and_does_not_call_api(monkeypatch, tmp_path):
    calls = []

    def fake_post(*args, **kwargs):
        calls.append(args)
        return MagicMock()

    monkeypatch.setattr(notion_client.requests, "post", fake_post)

    result = notion_client.upload_to_notion(
        briefing_path=tmp_path / "missing.md",
        items=[_sample_item()],
        total_collected=1,
    )

    assert calls == []
    assert result == EXPECTED_EMPTY


def test_upload_does_not_raise_when_api_completely_fails(monkeypatch, tmp_path):
    _set_notion_env(monkeypatch)

    def always_fail(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(notion_client.requests, "post", always_fail)

    briefing_file = tmp_path / "b.md"
    briefing_file.write_text("test")

    result = notion_client.upload_to_notion(
        briefing_path=briefing_file, items=[_sample_item()], total_collected=1
    )
    # daily lookup fails -> daily_created stays 0, no skip recorded.
    # per-item lookup fails -> items_failed increments.
    assert result["daily_created"] == 0
    assert result["daily_skipped"] == 0
    assert result["items_failed"] == 1


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------


def test_daily_briefing_properties_have_required_fields():
    props = notion_client.build_daily_briefing_properties(
        date_str="2026-05-17",
        total_collected=48,
        included=16,
        main_themes=["bim", "openbim", "embodied_carbon"],
        markdown="# Briefing body",
        github_url="https://github.com/u/r/blob/main/outputs/x.md",
    )

    assert props["Title"]["title"][0]["text"]["content"] == "Daily Briefing — 2026-05-17"
    assert props["Date"]["date"]["start"] == "2026-05-17"
    assert props["Total Items"]["number"] == 48.0
    assert props["Status"]["select"]["name"] == "Draft"


def test_research_item_properties_store_normalized_doi_and_url():
    item = _sample_item(
        doi="https://doi.org/10.1234/ABC",
        url="https://Example.com/Paper/",
    )
    props = notion_client.build_research_item_properties(
        item,
        why_it_matters="why",
        relevance_to_seongho="rel",
        summary_text="sum",
    )

    # DOI prefix stripped and lowercased.
    assert props["DOI"]["rich_text"][0]["text"]["content"] == "10.1234/abc"
    # URL trailing slash dropped, hostname lowercased.
    assert props["URL"]["url"] == "https://example.com/Paper"


def test_relevance_label_logic():
    assert notion_client._relevance_label(_sample_item(score=20, topics=[])) == "High"
    assert notion_client._relevance_label(_sample_item(score=3, topics=["structural_steel"])) == "High"
    assert notion_client._relevance_label(_sample_item(score=6, topics=[])) == "Medium"
    assert notion_client._relevance_label(_sample_item(score=2, topics=[])) == "Low"


# ---------------------------------------------------------------------------
# Daily briefing duplicate handling
# ---------------------------------------------------------------------------


def test_daily_briefing_created_when_no_duplicate(monkeypatch, tmp_path):
    _set_notion_env(monkeypatch)
    fake_post = _make_post_recorder(daily_results=[[]], research_results=[[]])
    monkeypatch.setattr(notion_client.requests, "post", fake_post)

    briefing = tmp_path / "b.md"
    briefing.write_text("# x")

    result = notion_client.upload_to_notion(
        briefing,
        [_sample_item()],
        total_collected=1,
        generated_at=datetime(2026, 5, 17, 8, 0),
    )

    assert result["daily_created"] == 1
    assert result["daily_skipped"] == 0


def test_daily_briefing_skipped_when_same_date_exists(monkeypatch, tmp_path, caplog):
    _set_notion_env(monkeypatch)
    fake_post = _make_post_recorder(
        daily_results=[[{"id": "existing-briefing"}]], research_results=[[]]
    )
    monkeypatch.setattr(notion_client.requests, "post", fake_post)

    briefing = tmp_path / "b.md"
    briefing.write_text("# x")

    with caplog.at_level("INFO"):
        result = notion_client.upload_to_notion(
            briefing,
            [_sample_item()],
            total_collected=1,
            generated_at=datetime(2026, 5, 17, 8, 0),
        )

    assert result["daily_created"] == 0
    assert result["daily_skipped"] == 1
    # Spec-mandated log message.
    assert "daily briefing already exists for 2026-05-17, skipped." in caplog.text


# ---------------------------------------------------------------------------
# Research items duplicate handling
# ---------------------------------------------------------------------------


def test_same_doi_item_is_skipped(monkeypatch, tmp_path):
    _set_notion_env(monkeypatch)
    fake_post = _make_post_recorder(
        daily_results=[[]], research_results=[[{"id": "existing"}]]
    )
    monkeypatch.setattr(notion_client.requests, "post", fake_post)

    briefing = tmp_path / "b.md"
    briefing.write_text("")

    result = notion_client.upload_to_notion(
        briefing, [_sample_item()], total_collected=1
    )

    assert result["items_skipped"] == 1
    assert result["items_uploaded"] == 0


def test_doi_match_is_case_insensitive(monkeypatch, tmp_path):
    """Notion query should use a lowercased DOI even when the item has an uppercased one."""
    _set_notion_env(monkeypatch)
    fake_post = _make_post_recorder(
        daily_results=[[]], research_results=[[{"id": "existing"}]]
    )
    monkeypatch.setattr(notion_client.requests, "post", fake_post)

    briefing = tmp_path / "b.md"
    briefing.write_text("")

    item = _sample_item(doi="10.1234/ABC")
    notion_client.upload_to_notion(briefing, [item], total_collected=1)

    research_queries = [
        c["json"] for c in fake_post.calls
        if c["url"].endswith("/databases/research-db/query")
    ]
    assert len(research_queries) == 1
    f = research_queries[0]["filter"]
    assert f["property"] == "DOI"
    assert f["rich_text"]["equals"] == "10.1234/abc"


def test_url_trailing_slash_does_not_cause_duplicate(monkeypatch, tmp_path):
    _set_notion_env(monkeypatch)
    fake_post = _make_post_recorder(
        daily_results=[[]], research_results=[[{"id": "existing"}]]
    )
    monkeypatch.setattr(notion_client.requests, "post", fake_post)

    briefing = tmp_path / "b.md"
    briefing.write_text("")

    item = _sample_item(doi=None, url="https://example.com/paper/")
    result = notion_client.upload_to_notion(briefing, [item], total_collected=1)

    assert result["items_skipped"] == 1
    research_queries = [
        c["json"] for c in fake_post.calls
        if c["url"].endswith("/databases/research-db/query")
    ]
    f = research_queries[0]["filter"]
    assert f["property"] == "URL"
    # Trailing slash dropped before query.
    assert f["url"]["equals"] == "https://example.com/paper"


def test_missing_doi_falls_back_to_url(monkeypatch, tmp_path):
    _set_notion_env(monkeypatch)
    fake_post = _make_post_recorder(
        daily_results=[[]], research_results=[[{"id": "existing"}]]
    )
    monkeypatch.setattr(notion_client.requests, "post", fake_post)

    briefing = tmp_path / "b.md"
    briefing.write_text("")

    item = _sample_item(doi=None, url="https://example.com/paper")
    notion_client.upload_to_notion(briefing, [item], total_collected=1)

    # Only one research query (URL-based). No DOI query was sent.
    research_queries = [
        c["json"] for c in fake_post.calls
        if c["url"].endswith("/databases/research-db/query")
    ]
    assert len(research_queries) == 1
    assert research_queries[0]["filter"]["property"] == "URL"


def test_missing_doi_and_url_falls_back_to_title(monkeypatch, tmp_path):
    _set_notion_env(monkeypatch)
    fake_post = _make_post_recorder(
        daily_results=[[]], research_results=[[{"id": "existing"}]]
    )
    monkeypatch.setattr(notion_client.requests, "post", fake_post)

    briefing = tmp_path / "b.md"
    briefing.write_text("")

    item = _sample_item(doi=None, url=None, title="My Paper Title")
    result = notion_client.upload_to_notion(briefing, [item], total_collected=1)

    assert result["items_skipped"] == 1
    research_queries = [
        c["json"] for c in fake_post.calls
        if c["url"].endswith("/databases/research-db/query")
    ]
    f = research_queries[0]["filter"]
    assert f["property"] == "Title"
    assert f["title"]["equals"] == "My Paper Title"


def test_no_duplicate_key_means_new_item_always_created(monkeypatch, tmp_path):
    """If DOI, URL and title are all missing, we have nothing to query and
    the item is treated as new."""
    _set_notion_env(monkeypatch)
    fake_post = _make_post_recorder(daily_results=[[]], research_results=[])
    monkeypatch.setattr(notion_client.requests, "post", fake_post)

    briefing = tmp_path / "b.md"
    briefing.write_text("")

    item = StandardItem(title="", source="test", doi=None, url=None)
    result = notion_client.upload_to_notion(briefing, [item], total_collected=1)

    assert result["items_uploaded"] == 1
    # Daily query + daily create + item create. No research-DB query.
    research_queries = [c for c in fake_post.calls if c["url"].endswith("/databases/research-db/query")]
    assert research_queries == []


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------


def test_query_failure_for_one_item_increments_items_failed(monkeypatch, tmp_path):
    _set_notion_env(monkeypatch)
    call_count = {"n": 0}

    def fake_post(url, **kwargs):
        call_count["n"] += 1
        mock = MagicMock()
        # Call 1: daily query (success, no result).
        # Call 2: daily create (success).
        # Call 3: research query for item A (FAIL).
        # Call 4: research query for item B (success, no result).
        # Call 5: research create for item B (success).
        if call_count["n"] == 3:
            mock.raise_for_status.side_effect = RuntimeError("query failed")
            return mock
        mock.raise_for_status.return_value = None
        if url.endswith("/query"):
            mock.json.return_value = {"results": []}
        else:
            mock.json.return_value = {"id": f"page-{call_count['n']}"}
        return mock

    monkeypatch.setattr(notion_client.requests, "post", fake_post)

    briefing = tmp_path / "b.md"
    briefing.write_text("")

    items = [
        _sample_item(title="A", doi="10.1/A", url="https://x/A"),
        _sample_item(title="B", doi="10.1/B", url="https://x/B"),
    ]
    result = notion_client.upload_to_notion(briefing, items, total_collected=2)

    assert result["items_failed"] == 1
    assert result["items_uploaded"] == 1


def test_item_create_failure_increments_items_failed_and_continues(monkeypatch, tmp_path):
    _set_notion_env(monkeypatch)
    call_count = {"n": 0}

    def fake_post(url, **kwargs):
        call_count["n"] += 1
        mock = MagicMock()
        # Call sequence: 1=daily query, 2=daily create, 3=A query, 4=A create (FAIL),
        # 5=B query, 6=B create.
        if call_count["n"] == 4:
            mock.raise_for_status.side_effect = RuntimeError("create failed")
            return mock
        mock.raise_for_status.return_value = None
        if url.endswith("/query"):
            mock.json.return_value = {"results": []}
        else:
            mock.json.return_value = {"id": f"page-{call_count['n']}"}
        return mock

    monkeypatch.setattr(notion_client.requests, "post", fake_post)

    briefing = tmp_path / "b.md"
    briefing.write_text("")

    items = [
        _sample_item(title="A", doi="10.1/A", url="https://x/A"),
        _sample_item(title="B", doi="10.1/B", url="https://x/B"),
    ]
    result = notion_client.upload_to_notion(briefing, items, total_collected=2)

    assert result["items_failed"] == 1
    assert result["items_uploaded"] == 1
    assert result["daily_created"] == 1


def test_daily_query_failure_does_not_crash_and_skips_creation(monkeypatch, tmp_path):
    _set_notion_env(monkeypatch)

    def fake_post(url, **kwargs):
        mock = MagicMock()
        if "/databases/daily-db/query" in url:
            mock.raise_for_status.side_effect = RuntimeError("daily query failed")
            return mock
        mock.raise_for_status.return_value = None
        if url.endswith("/query"):
            mock.json.return_value = {"results": []}
        else:
            mock.json.return_value = {"id": "page-x"}
        return mock

    monkeypatch.setattr(notion_client.requests, "post", fake_post)

    briefing = tmp_path / "b.md"
    briefing.write_text("")

    result = notion_client.upload_to_notion(
        briefing, [_sample_item()], total_collected=1
    )

    # Daily was not created (we don't risk a duplicate after a failed check)
    # but items continue normally.
    assert result["daily_created"] == 0
    assert result["daily_skipped"] == 0
    assert result["items_uploaded"] == 1


# ---------------------------------------------------------------------------
# Final log line
# ---------------------------------------------------------------------------


def test_final_log_line_has_required_counters(monkeypatch, tmp_path, caplog):
    _set_notion_env(monkeypatch)
    fake_post = _make_post_recorder(daily_results=[[]], research_results=[[]])
    monkeypatch.setattr(notion_client.requests, "post", fake_post)

    briefing = tmp_path / "b.md"
    briefing.write_text("")

    with caplog.at_level("INFO"):
        notion_client.upload_to_notion(briefing, [_sample_item()], total_collected=1)

    msg = caplog.text
    for token in (
        "daily_created=",
        "daily_skipped=",
        "items_uploaded=",
        "items_skipped=",
        "items_failed=",
    ):
        assert token in msg, f"missing in final log: {token}"


# ---------------------------------------------------------------------------
# GitHub URL helper
# ---------------------------------------------------------------------------


def test_github_output_url_uses_actions_env(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    url = notion_client._github_output_url(Path("outputs/2026-05-17_daily_briefing.md"))
    assert url == "https://github.com/owner/repo/blob/main/outputs/2026-05-17_daily_briefing.md"


def test_github_output_url_none_locally(monkeypatch):
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    assert notion_client._github_output_url(Path("outputs/x.md")) is None
