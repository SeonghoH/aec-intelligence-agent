"""Tests for the Unpaywall DOI → open-access PDF discovery."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from aec_intel_agent import full_text
from aec_intel_agent.models import StandardItem


# ---------------------------------------------------------------------------
# unpaywall_lookup
# ---------------------------------------------------------------------------


def _resp(status: int, payload: dict | None = None) -> MagicMock:
    mock = MagicMock()
    mock.status_code = status
    mock.json.return_value = payload or {}
    return mock


def test_unpaywall_returns_pdf_url_for_oa_doi():
    payload = {
        "is_oa": True,
        "best_oa_location": {
            "url_for_pdf": "https://repo.example.edu/paper.pdf",
            "url": "https://repo.example.edu/paper",
        },
    }
    with patch(
        "aec_intel_agent.full_text.requests.get", return_value=_resp(200, payload)
    ):
        url = full_text.unpaywall_lookup("10.1016/j.x.2026.000")
    assert url == "https://repo.example.edu/paper.pdf"


def test_unpaywall_falls_back_to_url_when_pdf_missing():
    payload = {
        "is_oa": True,
        "best_oa_location": {"url": "https://repo.example.edu/paper.html"},
    }
    with patch(
        "aec_intel_agent.full_text.requests.get", return_value=_resp(200, payload)
    ):
        url = full_text.unpaywall_lookup("10.1/x")
    assert url == "https://repo.example.edu/paper.html"


def test_unpaywall_returns_none_for_closed_access():
    payload = {"is_oa": False, "best_oa_location": None}
    with patch(
        "aec_intel_agent.full_text.requests.get", return_value=_resp(200, payload)
    ):
        url = full_text.unpaywall_lookup("10.1/closed")
    assert url is None


def test_unpaywall_returns_none_on_404():
    with patch(
        "aec_intel_agent.full_text.requests.get", return_value=_resp(404)
    ):
        url = full_text.unpaywall_lookup("10.9999/nope")
    assert url is None


def test_unpaywall_returns_none_on_network_error():
    with patch(
        "aec_intel_agent.full_text.requests.get",
        side_effect=ConnectionError("dns failure"),
    ):
        url = full_text.unpaywall_lookup("10.1/x")
    assert url is None


def test_unpaywall_returns_none_on_invalid_json():
    mock = MagicMock()
    mock.status_code = 200
    mock.json.side_effect = ValueError("nope")
    with patch("aec_intel_agent.full_text.requests.get", return_value=mock):
        url = full_text.unpaywall_lookup("10.1/x")
    assert url is None


def test_unpaywall_returns_none_for_empty_doi():
    assert full_text.unpaywall_lookup("") is None
    assert full_text.unpaywall_lookup(None) is None  # type: ignore[arg-type]


def test_unpaywall_strips_doi_url_prefix():
    """Should accept 'https://doi.org/10.x/y' and 'doi:10.x/y' too."""
    payload = {"is_oa": True, "best_oa_location": {"url_for_pdf": "https://x.pdf"}}
    with patch(
        "aec_intel_agent.full_text.requests.get", return_value=_resp(200, payload)
    ) as mock_get:
        full_text.unpaywall_lookup("https://doi.org/10.1/x")
    called_url = mock_get.call_args.args[0]
    assert called_url.endswith("/10.1/x")


def test_unpaywall_uses_env_email(monkeypatch):
    monkeypatch.setenv("UNPAYWALL_EMAIL", "real@user.edu")
    payload = {"is_oa": True, "best_oa_location": {"url_for_pdf": "https://x.pdf"}}
    with patch(
        "aec_intel_agent.full_text.requests.get", return_value=_resp(200, payload)
    ) as mock_get:
        full_text.unpaywall_lookup("10.1/x")
    assert mock_get.call_args.kwargs["params"]["email"] == "real@user.edu"


# ---------------------------------------------------------------------------
# detect_pdf_url integration
# ---------------------------------------------------------------------------


def test_detect_pdf_url_prefers_arxiv_over_unpaywall():
    """arXiv path runs first; Unpaywall should not even be called."""
    item = StandardItem(
        title="X", source="arxiv",
        url="http://arxiv.org/abs/2501.00001v1",
        doi="10.1/x",
    )
    with patch("aec_intel_agent.full_text.unpaywall_lookup") as mock_unp:
        url = full_text.detect_pdf_url(item)
    assert url.startswith("https://arxiv.org/pdf/")
    mock_unp.assert_not_called()


def test_detect_pdf_url_falls_back_to_unpaywall_for_doi():
    item = StandardItem(
        title="Closed-source paper",
        source="crossref",
        url="https://doi.org/10.1016/j.x.2026.000",
        doi="10.1016/j.x.2026.000",
    )
    with patch(
        "aec_intel_agent.full_text.unpaywall_lookup",
        return_value="https://repo.example.edu/paper.pdf",
    ):
        url = full_text.detect_pdf_url(item)
    assert url == "https://repo.example.edu/paper.pdf"


def test_detect_pdf_url_returns_none_when_unpaywall_finds_nothing():
    item = StandardItem(
        title="Paywalled", source="crossref",
        url="https://doi.org/10.1/closed", doi="10.1/closed",
    )
    with patch(
        "aec_intel_agent.full_text.unpaywall_lookup", return_value=None
    ):
        assert full_text.detect_pdf_url(item) is None


def test_detect_pdf_url_skips_unpaywall_when_no_doi():
    item = StandardItem(title="No DOI", source="crossref")
    with patch("aec_intel_agent.full_text.unpaywall_lookup") as mock_unp:
        assert full_text.detect_pdf_url(item) is None
    mock_unp.assert_not_called()
