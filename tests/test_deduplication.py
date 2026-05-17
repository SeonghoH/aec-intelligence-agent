from aec_intel_agent.deduplication import (
    deduplicate_items,
    normalize_doi,
    normalize_title,
    normalize_url,
)
from aec_intel_agent.models import StandardItem


def test_normalize_doi_lowercases_and_strips():
    assert normalize_doi(" 10.1234/ABC ") == "10.1234/abc"


def test_normalize_doi_strips_prefix():
    assert normalize_doi("https://doi.org/10.1234/ABC") == "10.1234/abc"


def test_normalize_doi_returns_none_for_empty():
    assert normalize_doi(None) is None
    assert normalize_doi("") is None
    assert normalize_doi("   ") is None


def test_normalize_url_removes_trailing_slash():
    assert normalize_url("https://example.com/paper/") == "https://example.com/paper"


def test_normalize_title_collapses_whitespace_and_lowercases():
    assert normalize_title("  My  Paper\tTitle\n") == "my paper title"


def test_normalize_title_returns_none_for_empty():
    assert normalize_title(None) is None
    assert normalize_title("   ") is None


def test_deduplicate_items_by_doi() -> None:
    items = [
        StandardItem(title="First", source="test", doi="https://doi.org/10.123/ABC"),
        StandardItem(title="Duplicate", source="test", doi="10.123/abc"),
    ]

    unique_items = deduplicate_items(items)

    assert [item.title for item in unique_items] == ["First"]


def test_deduplicate_items_by_url() -> None:
    items = [
        StandardItem(
            title="First",
            source="test",
            url="https://example.com/article?utm_source=newsletter",
        ),
        StandardItem(
            title="Duplicate",
            source="test",
            url="https://example.com/article/",
        ),
    ]

    unique_items = deduplicate_items(items)

    assert [item.title for item in unique_items] == ["First"]

