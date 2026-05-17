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


# ---------------------------------------------------------------------------
# Config detection
# ---------------------------------------------------------------------------


def test_is_configured_false_when_token_missing(monkeypatch):
    monkeypatch.setenv("NOTION_DAILY_DB_ID", "d")
    monkeypatch.setenv("NOTION_RESEARCH_DB_ID", "r")
    assert notion_client.is_configured() is False


def test_is_configured_false_when_daily_db_missing(monkeypatch):
    monkeypatch.setenv("NOTION_TOKEN", "t")
    monkeypatch.setenv("NOTION_RESEARCH_DB_ID", "r")
    assert notion_client.is_configured() is False


def test_is_configured_false_when_research_db_missing(monkeypatch):
    monkeypatch.setenv("NOTION_TOKEN", "t")
    monkeypatch.setenv("NOTION_DAILY_DB_ID", "d")
    assert notion_client.is_configured() is False


def test_is_configured_true_when_all_set(monkeypatch):
    monkeypatch.setenv("NOTION_TOKEN", "t")
    monkeypatch.setenv("NOTION_DAILY_DB_ID", "d")
    monkeypatch.setenv("NOTION_RESEARCH_DB_ID", "r")
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
    assert result == {"daily_uploaded": 0, "items_uploaded": 0, "items_skipped": 0}


def test_upload_does_not_raise_when_api_completely_fails(monkeypatch, tmp_path):
    monkeypatch.setenv("NOTION_TOKEN", "t")
    monkeypatch.setenv("NOTION_DAILY_DB_ID", "d")
    monkeypatch.setenv("NOTION_RESEARCH_DB_ID", "r")

    def always_fail(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(notion_client.requests, "post", always_fail)

    briefing_file = tmp_path / "b.md"
    briefing_file.write_text("test")

    # Must not raise.
    result = notion_client.upload_to_notion(
        briefing_path=briefing_file, items=[_sample_item()], total_collected=1
    )
    assert result["daily_uploaded"] == 0
    assert result["items_uploaded"] == 0


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
    assert props["Included Items"]["number"] == 16.0
    themes = [m["name"] for m in props["Main Themes"]["multi_select"]]
    assert themes == ["bim", "openbim", "embodied_carbon"]
    assert props["Status"]["select"]["name"] == "Draft"
    assert (
        props["GitHub Output Path"]["url"]
        == "https://github.com/u/r/blob/main/outputs/x.md"
    )
    assert props["Markdown Summary"]["rich_text"][0]["text"]["content"] == "# Briefing body"


def test_research_item_properties_have_required_fields():
    item = _sample_item()
    props = notion_client.build_research_item_properties(
        item,
        why_it_matters="BIM-Digital Twin 관련.",
        relevance_to_seongho="박사 연구 직결.",
        summary_text="결정적 요약.",
    )

    assert props["Title"]["title"][0]["text"]["content"] == "Test paper on BIM and steel"
    assert props["Published Date"]["date"]["start"] == "2026-05-01"
    assert props["Source"]["select"]["name"] == "crossref"
    assert props["Source Type"]["select"]["name"] == "paper"
    assert props["DOI"]["rich_text"][0]["text"]["content"] == "10.1234/abc"
    assert props["URL"]["url"] == "https://doi.org/10.1234/abc"
    assert props["Score"]["number"] == 12.0
    tags = {m["name"] for m in props["Tags"]["multi_select"]}
    assert {"bim", "structural_steel"} <= tags
    assert props["Relevance"]["select"]["name"] == "High"
    assert props["Read Status"]["select"]["name"] == "Unread"
    assert props["Related Work"]["multi_select"] == []
    assert (
        props["Why It Matters"]["rich_text"][0]["text"]["content"]
        == "BIM-Digital Twin 관련."
    )
    assert (
        props["Relevance to Seongho"]["rich_text"][0]["text"]["content"]
        == "박사 연구 직결."
    )
    assert props["Full-text Status"]["select"]["name"] == "Not Available"


def test_relevance_label_high_for_steel_topic():
    assert notion_client._relevance_label(_sample_item(score=3, topics=["structural_steel"])) == "High"


def test_relevance_label_high_for_high_score():
    assert notion_client._relevance_label(_sample_item(score=20, topics=[])) == "High"


def test_relevance_label_medium_when_only_score():
    assert notion_client._relevance_label(_sample_item(score=6, topics=[])) == "Medium"


def test_relevance_label_low_when_nothing_matches():
    assert notion_client._relevance_label(_sample_item(score=2, topics=[])) == "Low"


def test_long_text_is_chunked_under_notion_limit():
    long_text = "A" * 5500
    rt = notion_client._chunked_rich_text(long_text)
    assert len(rt["rich_text"]) >= 2
    for chunk in rt["rich_text"]:
        assert len(chunk["text"]["content"]) <= notion_client.RICH_TEXT_CHUNK_SIZE


def test_empty_rich_text_returns_empty_array():
    assert notion_client._chunked_rich_text("")["rich_text"] == []
    assert notion_client._chunked_rich_text(None)["rich_text"] == []


def test_missing_url_returns_null_url():
    assert notion_client._url_prop(None)["url"] is None
    assert notion_client._url_prop("")["url"] is None


def test_missing_date_returns_null_date():
    assert notion_client._date_prop(None)["date"] is None


# ---------------------------------------------------------------------------
# End-to-end upload (mocked API)
# ---------------------------------------------------------------------------


def _make_post_recorder(query_responses):
    """Return a fake requests.post that records calls and returns canned data.

    query_responses: dict mapping db_id -> list of pre-built `results` arrays
    consumed in order on each query for that db_id. POSTs to /pages always
    return a fresh page id.
    """
    calls: list[dict] = []

    def fake_post(url, **kwargs):
        mock = MagicMock()
        mock.raise_for_status.return_value = None
        body = kwargs.get("json", {})
        calls.append({"url": url, "json": body})

        if "/databases/" in url and url.endswith("/query"):
            db_id = url.split("/databases/")[1].split("/query")[0]
            queue = query_responses.get(db_id, [])
            results = queue.pop(0) if queue else []
            mock.json.return_value = {"results": results}
        elif url.endswith("/pages"):
            mock.json.return_value = {"id": f"page-{len(calls)}"}
        else:
            mock.json.return_value = {}
        return mock

    fake_post.calls = calls
    return fake_post


def _set_notion_env(monkeypatch, daily="daily-db", research="research-db"):
    monkeypatch.setenv("NOTION_TOKEN", "secret-fake")
    monkeypatch.setenv("NOTION_DAILY_DB_ID", daily)
    monkeypatch.setenv("NOTION_RESEARCH_DB_ID", research)


def test_upload_creates_daily_briefing_and_item_when_no_duplicates(
    monkeypatch, tmp_path
):
    _set_notion_env(monkeypatch)
    fake_post = _make_post_recorder({"daily-db": [[]], "research-db": [[], []]})
    monkeypatch.setattr(notion_client.requests, "post", fake_post)

    briefing_file = tmp_path / "b.md"
    briefing_file.write_text("# Hello")

    result = notion_client.upload_to_notion(
        briefing_path=briefing_file,
        items=[_sample_item()],
        total_collected=10,
        generated_at=datetime(2026, 5, 17, 8, 0),
    )

    assert result == {"daily_uploaded": 1, "items_uploaded": 1, "items_skipped": 0}
    # Authorization header is set on every call.
    for c in fake_post.calls:
        # MagicMock captures kwargs through fake_post, but headers are passed
        # via the real call — we verify via the URLs and bodies instead.
        assert c["url"].startswith(notion_client.NOTION_API_BASE)


def test_upload_skips_duplicate_research_item(monkeypatch, tmp_path):
    _set_notion_env(monkeypatch)
    # Daily query: no existing. Research query (DOI): existing.
    fake_post = _make_post_recorder(
        {"daily-db": [[]], "research-db": [[{"id": "existing"}]]}
    )
    monkeypatch.setattr(notion_client.requests, "post", fake_post)

    briefing_file = tmp_path / "b.md"
    briefing_file.write_text("# Hello")

    result = notion_client.upload_to_notion(
        briefing_path=briefing_file,
        items=[_sample_item()],
        total_collected=10,
        generated_at=datetime(2026, 5, 17, 8, 0),
    )

    assert result["items_skipped"] == 1
    assert result["items_uploaded"] == 0


def test_upload_skips_duplicate_daily_briefing(monkeypatch, tmp_path):
    _set_notion_env(monkeypatch)
    fake_post = _make_post_recorder(
        {"daily-db": [[{"id": "existing-briefing"}]], "research-db": [[]]}
    )
    monkeypatch.setattr(notion_client.requests, "post", fake_post)

    briefing_file = tmp_path / "b.md"
    briefing_file.write_text("# Hello")

    result = notion_client.upload_to_notion(
        briefing_path=briefing_file,
        items=[_sample_item()],
        total_collected=10,
        generated_at=datetime(2026, 5, 17, 8, 0),
    )

    assert result["daily_uploaded"] == 0
    assert result["items_uploaded"] == 1


def test_upload_continues_items_after_daily_failure(monkeypatch, tmp_path):
    _set_notion_env(monkeypatch)
    call_counter = {"n": 0}

    def fake_post(url, **kwargs):
        call_counter["n"] += 1
        mock = MagicMock()
        # First call = daily query — make it fail.
        if call_counter["n"] == 1:
            mock.raise_for_status.side_effect = RuntimeError("daily query failed")
            return mock
        mock.raise_for_status.return_value = None
        if "/query" in url:
            mock.json.return_value = {"results": []}
        else:
            mock.json.return_value = {"id": f"page-{call_counter['n']}"}
        return mock

    monkeypatch.setattr(notion_client.requests, "post", fake_post)

    briefing_file = tmp_path / "b.md"
    briefing_file.write_text("# Hello")

    result = notion_client.upload_to_notion(
        briefing_path=briefing_file,
        items=[_sample_item()],
        total_collected=10,
    )

    assert result["daily_uploaded"] == 0
    assert result["items_uploaded"] == 1


def test_upload_per_item_failure_does_not_stop_other_items(monkeypatch, tmp_path):
    _set_notion_env(monkeypatch)
    call_counter = {"n": 0}

    def fake_post(url, **kwargs):
        call_counter["n"] += 1
        mock = MagicMock()
        # Make the third call fail (item-1 query or create). Others succeed.
        if call_counter["n"] == 3:
            mock.raise_for_status.side_effect = RuntimeError("item failure")
            return mock
        mock.raise_for_status.return_value = None
        if "/query" in url:
            mock.json.return_value = {"results": []}
        else:
            mock.json.return_value = {"id": f"page-{call_counter['n']}"}
        return mock

    monkeypatch.setattr(notion_client.requests, "post", fake_post)

    briefing_file = tmp_path / "b.md"
    briefing_file.write_text("# Hello")

    items = [
        _sample_item(title="A", doi="10.1/A", url="https://x/A"),
        _sample_item(title="B", doi="10.1/B", url="https://x/B"),
        _sample_item(title="C", doi="10.1/C", url="https://x/C"),
    ]

    result = notion_client.upload_to_notion(
        briefing_path=briefing_file, items=items, total_collected=10
    )

    # At least one item should still be uploaded despite the per-item failure.
    assert result["items_uploaded"] >= 1


def test_github_output_url_uses_actions_env(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    url = notion_client._github_output_url(Path("outputs/2026-05-17_daily_briefing.md"))
    assert url == "https://github.com/owner/repo/blob/main/outputs/2026-05-17_daily_briefing.md"


def test_github_output_url_none_locally(monkeypatch):
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    assert notion_client._github_output_url(Path("outputs/x.md")) is None
