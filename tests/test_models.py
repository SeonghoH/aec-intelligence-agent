from datetime import date

from aec_intel_agent.models import StandardItem


def test_standard_item_accepts_minimal_fields() -> None:
    item = StandardItem(title="BIM paper", source="test")

    assert item.title == "BIM paper"
    assert item.source == "test"
    assert item.authors == []
    assert item.score == 0


def test_standard_item_parses_date_string() -> None:
    item = StandardItem(
        title="Digital twin article",
        source="test",
        published_date="2026-05-16",
    )

    assert item.published_date == date(2026, 5, 16)
    assert item.display_date == "2026-05-16"

