"""Tests for the Notion database setup script."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import setup_notion_databases as setup


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------


def test_daily_briefings_payload_has_required_properties():
    payload = setup.build_daily_briefings_payload("parent-page-123")

    assert payload["parent"] == {"type": "page_id", "page_id": "parent-page-123"}
    assert payload["title"][0]["text"]["content"] == "Daily Briefings"

    props = payload["properties"]
    assert "title" in props["Title"]
    assert "date" in props["Date"]
    assert "number" in props["Total Items"]
    assert "number" in props["Included Items"]
    assert "multi_select" in props["Main Themes"]
    assert "select" in props["Status"]
    assert "rich_text" in props["Markdown Summary"]
    assert "url" in props["GitHub Output Path"]


def test_research_items_payload_has_required_properties():
    payload = setup.build_research_items_payload("parent-page-456")

    assert payload["parent"] == {"type": "page_id", "page_id": "parent-page-456"}
    assert payload["title"][0]["text"]["content"] == "Research Items"

    props = payload["properties"]
    expected = {
        "Title": "title",
        "Published Date": "date",
        "Source": "select",
        "Source Type": "select",
        "DOI": "rich_text",
        "URL": "url",
        "Score": "number",
        "Tags": "multi_select",
        "Relevance": "select",
        "Read Status": "select",
        "Related Work": "multi_select",
        "Summary": "rich_text",
        "Why It Matters": "rich_text",
        "Relevance to Seongho": "rich_text",
        "Full-text Status": "select",
    }
    for name, expected_type in expected.items():
        assert name in props, f"missing property: {name}"
        assert expected_type in props[name], (
            f"property {name} should be of type {expected_type}, got {props[name]}"
        )


def test_research_items_payload_includes_full_text_url():
    payload = setup.build_research_items_payload("parent")
    props = payload["properties"]
    assert "Full-text URL" in props
    assert "url" in props["Full-text URL"]


def test_full_text_status_options_match_new_spec():
    payload = setup.build_research_items_payload("parent")
    options = [
        o["name"]
        for o in payload["properties"]["Full-text Status"]["select"]["options"]
    ]
    for expected in (
        "Not Attempted",
        "Open Access PDF Found",
        "Full Text Extracted",
        "PDF Download Failed",
        "PDF Text Extraction Failed",
        "Login Required / Skipped",
    ):
        assert expected in options, f"missing status option: {expected}"


def test_select_options_include_expected_values():
    payload = setup.build_research_items_payload("parent")
    props = payload["properties"]

    source_options = [o["name"] for o in props["Source"]["select"]["options"]]
    assert "crossref" in source_options
    assert "arxiv" in source_options

    type_options = [o["name"] for o in props["Source Type"]["select"]["options"]]
    assert "paper" in type_options
    assert "preprint" in type_options


# ---------------------------------------------------------------------------
# Env var validation
# ---------------------------------------------------------------------------


def test_missing_notion_token_exits_with_error(monkeypatch, capsys):
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    monkeypatch.setenv("NOTION_PARENT_PAGE_ID", "page-id")

    with pytest.raises(SystemExit) as excinfo:
        setup.main()
    assert excinfo.value.code == 1

    err = capsys.readouterr().err
    assert "NOTION_TOKEN" in err
    assert "not set" in err


def test_missing_parent_page_id_exits_with_error(monkeypatch, capsys):
    monkeypatch.setenv("NOTION_TOKEN", "fake-token-xyz")
    monkeypatch.delenv("NOTION_PARENT_PAGE_ID", raising=False)

    with pytest.raises(SystemExit) as excinfo:
        setup.main()
    assert excinfo.value.code == 1

    err = capsys.readouterr().err
    assert "NOTION_PARENT_PAGE_ID" in err
    # Token must not be echoed even though it was set.
    assert "fake-token-xyz" not in err


# ---------------------------------------------------------------------------
# Notion API call
# ---------------------------------------------------------------------------


def test_create_database_calls_notion_api_and_returns_id(monkeypatch):
    captured: dict = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["headers"] = kwargs.get("headers")
        captured["json"] = kwargs.get("json")
        mock = MagicMock()
        mock.raise_for_status.return_value = None
        mock.json.return_value = {"id": "db-abc-123", "object": "database"}
        return mock

    monkeypatch.setattr(setup.requests, "post", fake_post)

    payload = setup.build_daily_briefings_payload("page-id")
    db_id = setup.create_database("secret-token", payload)

    assert db_id == "db-abc-123"
    assert captured["url"] == setup.NOTION_API_URL
    assert captured["headers"]["Authorization"] == "Bearer secret-token"
    assert captured["headers"]["Notion-Version"] == setup.NOTION_VERSION
    assert captured["json"] == payload


def test_create_database_raises_when_response_missing_id(monkeypatch):
    def fake_post(url, **kwargs):
        mock = MagicMock()
        mock.raise_for_status.return_value = None
        mock.json.return_value = {"object": "database"}  # no "id"
        return mock

    monkeypatch.setattr(setup.requests, "post", fake_post)

    with pytest.raises(RuntimeError):
        setup.create_database("token", {"parent": {}})


def test_create_database_propagates_http_errors(monkeypatch):
    def fake_post(url, **kwargs):
        mock = MagicMock()
        mock.raise_for_status.side_effect = RuntimeError("401 Unauthorized")
        return mock

    monkeypatch.setattr(setup.requests, "post", fake_post)

    with pytest.raises(RuntimeError, match="401"):
        setup.create_database("token", {"parent": {}})


# ---------------------------------------------------------------------------
# End-to-end main()
# ---------------------------------------------------------------------------


def test_main_creates_both_databases_and_prints_ids(monkeypatch, capsys):
    monkeypatch.setenv("NOTION_TOKEN", "secret-fake-token-12345")
    monkeypatch.setenv("NOTION_PARENT_PAGE_ID", "parent-page-id-abc")

    calls: list[dict] = []

    def fake_post(url, **kwargs):
        calls.append(kwargs.get("json", {}))
        mock = MagicMock()
        mock.raise_for_status.return_value = None
        # Return different IDs for the two databases.
        idx = len(calls)
        mock.json.return_value = {"id": f"db-id-{idx}"}
        return mock

    monkeypatch.setattr(setup.requests, "post", fake_post)

    setup.main()

    captured = capsys.readouterr()
    assert "NOTION_DAILY_DB_ID=db-id-1" in captured.out
    assert "NOTION_RESEARCH_DB_ID=db-id-2" in captured.out

    # The token must never appear in stdout or stderr.
    assert "secret-fake-token-12345" not in captured.out
    assert "secret-fake-token-12345" not in captured.err

    # Both databases were posted with the correct parent page id.
    assert len(calls) == 2
    assert calls[0]["parent"]["page_id"] == "parent-page-id-abc"
    assert calls[1]["parent"]["page_id"] == "parent-page-id-abc"
    assert calls[0]["title"][0]["text"]["content"] == "Daily Briefings"
    assert calls[1]["title"][0]["text"]["content"] == "Research Items"
