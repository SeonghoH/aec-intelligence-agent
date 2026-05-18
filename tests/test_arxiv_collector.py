"""Tests for the arXiv collector using mocked HTTP responses."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from aec_intel_agent.collectors.arxiv import ArxivCollector


def _recent_date(days_ago: int = 1) -> str:
    """Return an ISO-8601 date string N days before today, for mock fixtures."""
    return (date.today() - timedelta(days=days_ago)).isoformat() + "T00:00:00Z"


def _arxiv_atom_response() -> str:
    return f"""\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2501.00001v1</id>
    <title>AI-driven digital twin monitoring for construction sites</title>
    <summary>We present a machine learning approach for digital twin
    monitoring of construction sites using sensor data.</summary>
    <published>{_recent_date(1)}</published>
    <author><name>Alice Chen</name></author>
    <author><name>Bob Kim</name></author>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2501.00002v1</id>
    <title>Parametric BIM for structural steel design</title>
    <summary>Parametric design workflows integrated with BIM for steel frame structures.</summary>
    <published>{_recent_date(2)}</published>
    <author><name>Carol Lee</name></author>
  </entry>
  <entry>
    <id></id>
    <title></title>
    <summary></summary>
    <published>{_recent_date(1)}</published>
  </entry>
</feed>
"""


def _mock_get(url, **kwargs):
    mock = MagicMock()
    mock.raise_for_status.return_value = None
    mock.text = _arxiv_atom_response()
    return mock


def _keywords():
    return {"topics": {"ai_in_construction": ["AI in construction"]}}


@patch("aec_intel_agent.collectors.arxiv.requests.get", side_effect=_mock_get)
def test_arxiv_returns_standard_items(mock_get):
    collector = ArxivCollector(keywords_config=_keywords())
    items = collector.collect()

    assert len(items) == 2
    assert items[0].title == "AI-driven digital twin monitoring for construction sites"
    assert items[0].source == "arxiv"
    assert items[0].url == "http://arxiv.org/abs/2501.00001v1"
    assert items[0].item_type == "preprint"
    assert items[0].published_date is not None
    assert items[0].published_date >= date.today() - timedelta(days=3)
    assert "Alice Chen" in items[0].authors


@patch("aec_intel_agent.collectors.arxiv.requests.get", side_effect=_mock_get)
def test_arxiv_deduplicates_by_id(mock_get):
    keywords = {"topics": {"bim": ["BIM"], "digital_twin": ["digital twin"]}}
    collector = ArxivCollector(keywords_config=keywords)
    items = collector.collect()

    urls = [item.url for item in items]
    assert len(urls) == len(set(urls))


@patch("aec_intel_agent.collectors.arxiv.requests.get", side_effect=_mock_get)
def test_arxiv_skips_entries_without_id_or_title(mock_get):
    collector = ArxivCollector(keywords_config=_keywords())
    items = collector.collect()

    for item in items:
        assert item.title
        assert item.url


@patch(
    "aec_intel_agent.collectors.arxiv.requests.get",
    side_effect=Exception("connection refused"),
)
def test_arxiv_handles_api_error_gracefully(mock_get):
    collector = ArxivCollector(keywords_config=_keywords())
    items = collector.collect()
    assert items == []


@patch("aec_intel_agent.collectors.arxiv.requests.get", side_effect=_mock_get)
def test_arxiv_stores_raw_metadata_and_source_type(mock_get):
    collector = ArxivCollector(keywords_config=_keywords())
    item = collector.collect()[0]

    assert item.metadata.get("source_type") == "preprint"
    assert item.item_type == "preprint"
    raw = item.metadata.get("raw")
    assert isinstance(raw, dict)
    assert raw.get("id") == "http://arxiv.org/abs/2501.00001v1"
