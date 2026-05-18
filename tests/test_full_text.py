"""Tests for the full-text discovery and extraction module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

from aec_intel_agent import full_text
from aec_intel_agent.models import StandardItem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _arxiv_item(**overrides) -> StandardItem:
    defaults = dict(
        title="Test arXiv paper",
        source="arxiv",
        url="http://arxiv.org/abs/2501.00001v1",
        item_type="preprint",
        score=100,
        metadata={"source_type": "preprint"},
    )
    defaults.update(overrides)
    return StandardItem(**defaults)


def _pdf_item(**overrides) -> StandardItem:
    defaults = dict(
        title="Direct PDF item",
        source="crossref",
        url="https://example.com/paper.pdf",
        item_type="paper",
        score=85,
        metadata={"source_type": "paper"},
    )
    defaults.update(overrides)
    return StandardItem(**defaults)


class _FakePage:
    def __init__(self, text: str):
        self._text = text

    def extract_text(self) -> str:
        return self._text


class _FakePdfReader:
    def __init__(self, pages):
        self.pages = pages


def _mock_pdf_get(monkeypatch, pdf_bytes: bytes = b"%PDF-fake"):
    def fake_get(url, **kwargs):
        mock = MagicMock()
        mock.raise_for_status.return_value = None
        mock.headers = {"Content-Type": "application/pdf"}
        mock.iter_content.return_value = [pdf_bytes]
        return mock
    monkeypatch.setattr(full_text.requests, "get", fake_get)


def _mock_pdf_reader(monkeypatch, pages_text):
    fake_reader = _FakePdfReader([_FakePage(t) for t in pages_text])
    monkeypatch.setattr(full_text.pypdf, "PdfReader", lambda *a, **kw: fake_reader)


# ---------------------------------------------------------------------------
# Env var defaults
# ---------------------------------------------------------------------------


def test_max_items_defaults_to_3(monkeypatch):
    monkeypatch.delenv("FULL_TEXT_MAX_ITEMS", raising=False)
    assert full_text.get_max_items() == 3


def test_max_items_reads_env_when_valid(monkeypatch):
    monkeypatch.setenv("FULL_TEXT_MAX_ITEMS", "10")
    assert full_text.get_max_items() == 10


def test_max_items_falls_back_on_invalid_env(monkeypatch):
    monkeypatch.setenv("FULL_TEXT_MAX_ITEMS", "not-a-number")
    assert full_text.get_max_items() == 3


def test_max_chars_defaults_to_60000(monkeypatch):
    monkeypatch.delenv("FULL_TEXT_MAX_CHARS", raising=False)
    assert full_text.get_max_chars() == 60000


def test_max_chars_reads_env_when_valid(monkeypatch):
    monkeypatch.setenv("FULL_TEXT_MAX_CHARS", "5000")
    assert full_text.get_max_chars() == 5000


# ---------------------------------------------------------------------------
# Candidate selection
# ---------------------------------------------------------------------------


def test_select_candidates_filters_by_score():
    items = [
        _arxiv_item(title="low", score=50, url="http://arxiv.org/abs/2501.10001v1"),
        _arxiv_item(title="exact", score=80, url="http://arxiv.org/abs/2501.10002v1"),
        _arxiv_item(title="high", score=120, url="http://arxiv.org/abs/2501.10003v1"),
    ]
    titles = [i.title for i in full_text.select_candidates(items, max_items=10)]
    assert "low" not in titles
    assert "exact" in titles
    assert "high" in titles


def test_select_candidates_filters_non_paper_or_preprint():
    items = [
        StandardItem(
            title="article",
            source="news",
            score=100,
            item_type="article",
            metadata={"source_type": "article"},
        ),
        _arxiv_item(title="preprint"),
        _pdf_item(title="paper"),
    ]
    titles = [i.title for i in full_text.select_candidates(items, max_items=10)]
    assert "article" not in titles
    assert {"preprint", "paper"} <= set(titles)


def test_select_candidates_respects_max_items_arg():
    items = [
        _arxiv_item(
            title=f"p{i}", score=100, url=f"http://arxiv.org/abs/2501.1000{i}v1"
        )
        for i in range(5)
    ]
    assert len(full_text.select_candidates(items, max_items=2)) == 2


def test_select_candidates_uses_env_when_max_not_passed(monkeypatch):
    monkeypatch.setenv("FULL_TEXT_MAX_ITEMS", "1")
    items = [
        _arxiv_item(title=f"p{i}", url=f"http://arxiv.org/abs/2501.2000{i}v1")
        for i in range(3)
    ]
    assert len(full_text.select_candidates(items)) == 1


def test_select_candidates_returns_empty_when_max_zero(monkeypatch):
    items = [_arxiv_item()]
    assert full_text.select_candidates(items, max_items=0) == []


# ---------------------------------------------------------------------------
# PDF URL detection
# ---------------------------------------------------------------------------


def test_detect_arxiv_pdf_url_with_version():
    item = _arxiv_item(url="http://arxiv.org/abs/2501.00001v2")
    assert full_text.detect_pdf_url(item) == "https://arxiv.org/pdf/2501.00001.pdf"


def test_detect_arxiv_pdf_url_without_version():
    item = _arxiv_item(url="https://arxiv.org/abs/2501.00001")
    assert full_text.detect_pdf_url(item) == "https://arxiv.org/pdf/2501.00001.pdf"


def test_detect_arxiv_from_pdf_link_form():
    item = _arxiv_item(url="https://arxiv.org/pdf/2501.00001v3.pdf")
    # arXiv pattern preferred; the pdf/ form is also recognized.
    assert full_text.detect_pdf_url(item) == "https://arxiv.org/pdf/2501.00001.pdf"


def test_detect_direct_pdf_url():
    assert (
        full_text.detect_pdf_url(_pdf_item(url="https://example.com/paper.pdf"))
        == "https://example.com/paper.pdf"
    )


def test_detect_non_pdf_url_returns_none():
    item = StandardItem(
        title="x",
        source="crossref",
        url="https://springer.com/paper",
        score=100,
        item_type="paper",
    )
    assert full_text.detect_pdf_url(item) is None


def test_detect_no_url_returns_none():
    item = StandardItem(title="x", source="crossref", score=100, item_type="paper")
    assert full_text.detect_pdf_url(item) is None


# ---------------------------------------------------------------------------
# download_pdf
# ---------------------------------------------------------------------------


def test_download_pdf_returns_bytes(monkeypatch):
    def fake_get(url, **kwargs):
        mock = MagicMock()
        mock.raise_for_status.return_value = None
        mock.headers = {"Content-Type": "application/pdf"}
        mock.iter_content.return_value = [b"%PDF-1.4", b"-chunk2"]
        return mock
    monkeypatch.setattr(full_text.requests, "get", fake_get)

    assert full_text.download_pdf("https://x/y.pdf") == b"%PDF-1.4-chunk2"


def test_download_pdf_rejects_html_response(monkeypatch):
    def fake_get(url, **kwargs):
        mock = MagicMock()
        mock.raise_for_status.return_value = None
        mock.headers = {"Content-Type": "text/html; charset=utf-8"}
        return mock
    monkeypatch.setattr(full_text.requests, "get", fake_get)

    with pytest.raises(ValueError, match="HTML"):
        full_text.download_pdf("https://x/y.pdf")


def test_download_pdf_enforces_size_limit(monkeypatch):
    def fake_get(url, **kwargs):
        mock = MagicMock()
        mock.raise_for_status.return_value = None
        mock.headers = {"Content-Type": "application/pdf"}
        mock.iter_content.return_value = [b"x" * 11_000_000]
        return mock
    monkeypatch.setattr(full_text.requests, "get", fake_get)

    with pytest.raises(ValueError, match="size"):
        full_text.download_pdf("https://x/y.pdf", max_size=10 * 1024 * 1024)


# ---------------------------------------------------------------------------
# extract_text
# ---------------------------------------------------------------------------


def test_extract_text_concatenates_pages(monkeypatch):
    _mock_pdf_reader(monkeypatch, ["page one", "page two"])
    result = full_text.extract_text(b"%PDF")
    assert "page one" in result
    assert "page two" in result


def test_extract_text_caps_at_max_chars(monkeypatch):
    _mock_pdf_reader(monkeypatch, ["a" * 100, "b" * 100, "c" * 100])
    result = full_text.extract_text(b"%PDF", max_chars=150)
    assert len(result) <= 150


def test_extract_text_skips_pages_that_raise(monkeypatch):
    class _ExplodingPage:
        def extract_text(self):
            raise RuntimeError("bad page")
    reader = _FakePdfReader([_ExplodingPage(), _FakePage("good content")])
    monkeypatch.setattr(full_text.pypdf, "PdfReader", lambda *a, **kw: reader)

    result = full_text.extract_text(b"%PDF")
    assert "good content" in result


# ---------------------------------------------------------------------------
# process_item
# ---------------------------------------------------------------------------


def test_process_item_marks_login_required_when_no_pdf_url():
    item = StandardItem(
        title="paywalled",
        source="crossref",
        url="https://springer.com/paper",
        score=100,
        item_type="paper",
        metadata={"source_type": "paper"},
    )
    updated = full_text.process_item(item)
    assert updated.full_text_status == full_text.STATUS_LOGIN_REQUIRED
    assert updated.full_text_url is None


def test_process_item_records_download_failure(monkeypatch):
    def boom(*a, **kw):
        raise requests.exceptions.Timeout()
    monkeypatch.setattr(full_text.requests, "get", boom)

    updated = full_text.process_item(_arxiv_item())
    assert updated.full_text_status == full_text.STATUS_DOWNLOAD_FAILED
    assert updated.full_text_url == "https://arxiv.org/pdf/2501.00001.pdf"


def test_process_item_records_extraction_failure(monkeypatch):
    _mock_pdf_get(monkeypatch)

    def fake_reader(*a, **kw):
        raise RuntimeError("corrupt pdf")
    monkeypatch.setattr(full_text.pypdf, "PdfReader", fake_reader)

    updated = full_text.process_item(_arxiv_item())
    assert updated.full_text_status == full_text.STATUS_EXTRACTION_FAILED


def test_process_item_records_extraction_failure_on_empty_text(monkeypatch):
    _mock_pdf_get(monkeypatch)
    _mock_pdf_reader(monkeypatch, ["", "   ", ""])

    updated = full_text.process_item(_arxiv_item())
    assert updated.full_text_status == full_text.STATUS_EXTRACTION_FAILED


def test_process_item_success_writes_debug_file(monkeypatch, tmp_path):
    _mock_pdf_get(monkeypatch)
    _mock_pdf_reader(monkeypatch, ["Extracted body text."])

    debug_dir = tmp_path / "fulltext"
    updated = full_text.process_item(_arxiv_item(), debug_dir=debug_dir)

    assert updated.full_text_status == full_text.STATUS_FULL_TEXT_EXTRACTED
    assert updated.full_text_url == "https://arxiv.org/pdf/2501.00001.pdf"
    files = list(debug_dir.glob("*.txt"))
    assert len(files) == 1
    assert "Extracted body text." in files[0].read_text(encoding="utf-8")


def test_process_item_success_without_debug_dir(monkeypatch):
    _mock_pdf_get(monkeypatch)
    _mock_pdf_reader(monkeypatch, ["page content"])

    updated = full_text.process_item(_arxiv_item(), debug_dir=None)
    assert updated.full_text_status == full_text.STATUS_FULL_TEXT_EXTRACTED
    assert updated.full_text_path is None


# ---------------------------------------------------------------------------
# process_items
# ---------------------------------------------------------------------------


def test_process_items_only_processes_candidates(monkeypatch):
    request_count = {"n": 0}

    def fake_get(*a, **kw):
        request_count["n"] += 1
        mock = MagicMock()
        mock.raise_for_status.return_value = None
        mock.headers = {"Content-Type": "application/pdf"}
        mock.iter_content.return_value = [b"%PDF"]
        return mock

    monkeypatch.setattr(full_text.requests, "get", fake_get)
    _mock_pdf_reader(monkeypatch, ["page"])

    items = [
        _arxiv_item(
            title="high",
            score=100,
            url="http://arxiv.org/abs/2501.30001v1",
        ),
        _arxiv_item(
            title="low",
            score=10,
            url="http://arxiv.org/abs/2501.30002v1",
        ),
    ]
    out = full_text.process_items(items)

    assert request_count["n"] == 1
    assert out[0].full_text_status == full_text.STATUS_FULL_TEXT_EXTRACTED
    assert out[1].full_text_status == "Not Attempted"


def test_process_items_handles_per_item_failure(monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("network down")

    monkeypatch.setattr(full_text.requests, "get", boom)

    items = [_arxiv_item(score=100)]
    out = full_text.process_items(items)
    assert out[0].full_text_status == full_text.STATUS_DOWNLOAD_FAILED


def test_process_items_returns_input_when_no_candidates():
    items = [_arxiv_item(score=10)]  # below threshold
    out = full_text.process_items(items)
    assert [i.title for i in out] == [i.title for i in items]
    assert all(i.full_text_status == "Not Attempted" for i in out)


def test_process_items_respects_max_items_env(monkeypatch):
    monkeypatch.setenv("FULL_TEXT_MAX_ITEMS", "1")

    request_count = {"n": 0}

    def fake_get(*a, **kw):
        request_count["n"] += 1
        mock = MagicMock()
        mock.raise_for_status.return_value = None
        mock.headers = {"Content-Type": "application/pdf"}
        mock.iter_content.return_value = [b"%PDF"]
        return mock

    monkeypatch.setattr(full_text.requests, "get", fake_get)
    _mock_pdf_reader(monkeypatch, ["x"])

    items = [
        _arxiv_item(
            title=f"p{i}", score=100, url=f"http://arxiv.org/abs/2501.4000{i}v1"
        )
        for i in range(3)
    ]
    full_text.process_items(items)
    assert request_count["n"] == 1


# ---------------------------------------------------------------------------
# Main pipeline integration
# ---------------------------------------------------------------------------


def test_main_pipeline_does_not_crash_when_full_text_fails(monkeypatch, tmp_path):
    """End-to-end: even if full-text processing raises catastrophically,
    Markdown briefing is still written."""
    from unittest.mock import patch
    from datetime import date
    from aec_intel_agent.main import build_briefing

    sample = [
        StandardItem(
            title="Open Access Paper on BIM and openBIM",
            source="arxiv",
            url="http://arxiv.org/abs/2501.99999v1",
            item_type="preprint",
            published_date=date(2026, 5, 1),
            summary="BIM and openBIM study.",
            metadata={"source_type": "preprint"},
        )
    ]

    # Simulate a catastrophic, non-caught failure inside full_text.
    def boom(*args, **kwargs):
        raise RuntimeError("full text crashed unexpectedly")

    monkeypatch.setattr(
        "aec_intel_agent.main.run_full_text_pipeline", boom
    )

    with patch(
        "aec_intel_agent.main.CrossrefCollector.collect", return_value=sample
    ), patch("aec_intel_agent.main.ArxivCollector.collect", return_value=[]):
        output_path = build_briefing(
            config_dir="config",
            output_dir=str(tmp_path),
            seen_items_path=str(tmp_path / "seen.json"),
        )

    assert output_path.exists()
    content = output_path.read_text(encoding="utf-8")
    assert "Open Access Paper on BIM and openBIM" in content
