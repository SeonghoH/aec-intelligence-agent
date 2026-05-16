"""Tests for the Crossref collector using mocked HTTP responses."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from aec_intel_agent.collectors.crossref import CrossrefCollector

CROSSREF_RESPONSE = {
    "status": "ok",
    "message": {
        "items": [
            {
                "DOI": "10.1234/bim-steel-2026",
                "title": ["BIM workflows for structural steel"],
                "URL": "https://doi.org/10.1234/bim-steel-2026",
                "abstract": "<jats:p>This study examines BIM and LCA for steel construction.</jats:p>",
                "published": {"date-parts": [[2026, 4, 15]]},
                "author": [
                    {"given": "Jane", "family": "Smith"},
                    {"given": "John", "family": "Doe"},
                ],
                "type": "journal-article",
            },
            {
                "DOI": "",
                "title": [],
                "URL": None,
                "abstract": "",
                "published": {},
                "author": [],
                "type": "journal-article",
            },
        ]
    },
}


def _mock_get(url, **kwargs):
    mock = MagicMock()
    mock.raise_for_status.return_value = None
    mock.json.return_value = CROSSREF_RESPONSE
    return mock


def _keywords():
    return {"topics": {"bim": ["BIM", "building information modeling"]}}


@patch("aec_intel_agent.collectors.crossref.requests.get", side_effect=_mock_get)
def test_crossref_returns_standard_items(mock_get):
    collector = CrossrefCollector(keywords_config=_keywords())
    items = collector.collect()

    assert len(items) == 1
    item = items[0]
    assert item.title == "BIM workflows for structural steel"
    assert item.source == "crossref"
    assert item.doi == "10.1234/bim-steel-2026"
    assert item.url == "https://doi.org/10.1234/bim-steel-2026"
    assert item.published_date is not None
    assert item.published_date.year == 2026
    assert "Jane Smith" in item.authors
    assert "LCA" in item.summary or "BIM" in item.summary


@patch("aec_intel_agent.collectors.crossref.requests.get", side_effect=_mock_get)
def test_crossref_strips_jats_tags(mock_get):
    collector = CrossrefCollector(keywords_config=_keywords())
    items = collector.collect()

    assert "<jats:p>" not in items[0].summary
    assert "This study" in items[0].summary


@patch("aec_intel_agent.collectors.crossref.requests.get", side_effect=_mock_get)
def test_crossref_deduplicates_by_doi(mock_get):
    # Two topics both query the API, returning the same DOI each time.
    keywords = {"topics": {"bim": ["BIM"], "openbim": ["IFC"]}}
    collector = CrossrefCollector(keywords_config=keywords)
    items = collector.collect()

    dois = [item.doi for item in items]
    assert len(dois) == len(set(dois))


@patch(
    "aec_intel_agent.collectors.crossref.requests.get",
    side_effect=Exception("timeout"),
)
def test_crossref_handles_api_error_gracefully(mock_get):
    collector = CrossrefCollector(keywords_config=_keywords())
    items = collector.collect()
    assert items == []


@patch("aec_intel_agent.collectors.crossref.requests.get", side_effect=_mock_get)
def test_crossref_stores_raw_metadata_and_source_type(mock_get):
    collector = CrossrefCollector(keywords_config=_keywords())
    item = collector.collect()[0]

    assert item.metadata.get("source_type") == "paper"
    assert item.item_type == "paper"
    raw = item.metadata.get("raw")
    assert isinstance(raw, dict)
    assert raw.get("DOI") == "10.1234/bim-steel-2026"
