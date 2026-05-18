"""Tests for the seen-items persistence module."""

from __future__ import annotations

import json
from pathlib import Path

from aec_intel_agent.models import StandardItem
from aec_intel_agent.seen_items import (
    filter_unseen,
    load_seen,
    mark_seen,
    save_seen,
)


def _item(**kw) -> StandardItem:
    defaults = {"title": "T", "source": "test"}
    return StandardItem(**{**defaults, **kw})


def test_load_returns_empty_set_when_file_missing(tmp_path: Path) -> None:
    assert load_seen(tmp_path / "nope.json") == set()


def test_save_then_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "seen.json"
    save_seen({"doi:10.1/a", "url:https://x.test/p"}, path)
    assert load_seen(path) == {"doi:10.1/a", "url:https://x.test/p"}


def test_save_writes_sorted_keys_for_stable_diffs(tmp_path: Path) -> None:
    path = tmp_path / "seen.json"
    save_seen({"b", "a", "c"}, path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["keys"] == ["a", "b", "c"]


def test_corrupt_file_returns_empty_set(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("not json at all", encoding="utf-8")
    assert load_seen(path) == set()


def test_filter_unseen_separates_by_doi() -> None:
    a = _item(title="A", doi="10.1/A")
    b = _item(title="B", doi="10.1/B")
    seen = {"doi:10.1/a"}  # lowercase matches normalize_doi
    fresh, repeats = filter_unseen([a, b], seen)
    assert [i.title for i in fresh] == ["B"]
    assert [i.title for i in repeats] == ["A"]


def test_filter_unseen_matches_by_url_when_no_doi() -> None:
    a = _item(title="A", url="https://example.com/paper")
    seen = {"url:https://example.com/paper"}
    fresh, repeats = filter_unseen([a], seen)
    assert fresh == []
    assert len(repeats) == 1


def test_filter_unseen_matches_by_normalized_title_as_fallback() -> None:
    a = _item(title="  Multi    Space   Title  ")
    seen = {"title:multi space title"}
    fresh, repeats = filter_unseen([a], seen)
    assert fresh == []
    assert len(repeats) == 1


def test_mark_seen_adds_doi_url_and_title_keys() -> None:
    item = _item(
        title="Cool Paper",
        doi="10.1/x",
        url="https://x.test/p",
    )
    keys = mark_seen([item], set())
    assert "doi:10.1/x" in keys
    assert "url:https://x.test/p" in keys
    assert "title:cool paper" in keys


def test_mark_seen_preserves_existing_keys() -> None:
    existing = {"doi:10.9/old"}
    item = _item(title="New", doi="10.1/new")
    keys = mark_seen([item], existing)
    assert "doi:10.9/old" in keys
    assert "doi:10.1/new" in keys
