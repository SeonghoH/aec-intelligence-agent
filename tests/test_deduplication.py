from aec_intel_agent.deduplication import deduplicate_items
from aec_intel_agent.models import StandardItem


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

