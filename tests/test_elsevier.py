"""Tests for the Elsevier ScienceDirect TDM integration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from aec_intel_agent import full_text
from aec_intel_agent.models import StandardItem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resp(status: int, payload: dict | None = None) -> MagicMock:
    mock = MagicMock()
    mock.status_code = status
    mock.json.return_value = payload or {}
    return mock


def _elsevier_payload(text: str) -> dict:
    return {"full-text-retrieval-response": {"originalText": text}}


def _crossref_item(doi: str, **overrides) -> StandardItem:
    defaults = dict(
        title="An Elsevier paper",
        source="crossref",
        url=f"https://doi.org/{doi}",
        item_type="paper",
        doi=doi,
        score=85,
        metadata={"source_type": "paper"},
    )
    defaults.update(overrides)
    return StandardItem(**defaults)


# ---------------------------------------------------------------------------
# is_elsevier_doi
# ---------------------------------------------------------------------------


def test_is_elsevier_doi_recognizes_10_1016_prefix():
    assert full_text.is_elsevier_doi("10.1016/j.aei.2026.104619")
    assert full_text.is_elsevier_doi("https://doi.org/10.1016/j.foo.2026.000")
    assert full_text.is_elsevier_doi("doi:10.1016/j.foo")


def test_is_elsevier_doi_rejects_other_publishers():
    assert not full_text.is_elsevier_doi("10.1007/s11831-020-09445-x")  # Springer
    assert not full_text.is_elsevier_doi("10.1111/cgf.14000")  # Wiley
    assert not full_text.is_elsevier_doi("10.1109/TPAMI.2020.000")  # IEEE
    assert not full_text.is_elsevier_doi(None)
    assert not full_text.is_elsevier_doi("")


# ---------------------------------------------------------------------------
# fetch_elsevier_text
# ---------------------------------------------------------------------------


def test_fetch_elsevier_text_returns_body_on_200():
    payload = _elsevier_payload("Full article text here.")
    with patch(
        "aec_intel_agent.full_text.requests.get", return_value=_resp(200, payload)
    ):
        text = full_text.fetch_elsevier_text(
            "10.1016/j.x.2026.000", api_key="fake"
        )
    assert text == "Full article text here."


def test_fetch_elsevier_text_sends_apikey_header():
    payload = _elsevier_payload("body")
    with patch(
        "aec_intel_agent.full_text.requests.get", return_value=_resp(200, payload)
    ) as mock_get:
        full_text.fetch_elsevier_text("10.1016/j.x", api_key="my-real-key")
    headers = mock_get.call_args.kwargs["headers"]
    assert headers["X-ELS-APIKey"] == "my-real-key"


def test_fetch_elsevier_text_returns_none_without_key(monkeypatch):
    # No ELSEVIER_API_KEY env var, no explicit api_key arg.
    assert full_text.fetch_elsevier_text("10.1016/j.x") is None


def test_fetch_elsevier_text_returns_none_on_404():
    with patch(
        "aec_intel_agent.full_text.requests.get", return_value=_resp(404)
    ):
        text = full_text.fetch_elsevier_text("10.1016/j.unknown", api_key="fake")
    assert text is None


def test_fetch_elsevier_text_returns_none_on_401():
    with patch(
        "aec_intel_agent.full_text.requests.get", return_value=_resp(401)
    ):
        text = full_text.fetch_elsevier_text("10.1016/j.x", api_key="bad-key")
    assert text is None


def test_fetch_elsevier_text_returns_none_on_network_error():
    with patch(
        "aec_intel_agent.full_text.requests.get",
        side_effect=ConnectionError("dns"),
    ):
        text = full_text.fetch_elsevier_text("10.1016/j.x", api_key="fake")
    assert text is None


def test_fetch_elsevier_text_returns_none_when_body_empty():
    with patch(
        "aec_intel_agent.full_text.requests.get",
        return_value=_resp(200, _elsevier_payload("")),
    ):
        text = full_text.fetch_elsevier_text("10.1016/j.x", api_key="fake")
    assert text is None


def test_fetch_elsevier_text_returns_none_on_unexpected_json_shape():
    with patch(
        "aec_intel_agent.full_text.requests.get",
        return_value=_resp(200, {"unexpected": "shape"}),
    ):
        text = full_text.fetch_elsevier_text("10.1016/j.x", api_key="fake")
    assert text is None


def test_fetch_elsevier_text_strips_doi_url_prefix():
    payload = _elsevier_payload("body")
    with patch(
        "aec_intel_agent.full_text.requests.get", return_value=_resp(200, payload)
    ) as mock_get:
        full_text.fetch_elsevier_text(
            "https://doi.org/10.1016/j.x", api_key="fake"
        )
    called_url = mock_get.call_args.args[0]
    assert called_url.endswith("/10.1016/j.x")


def test_fetch_elsevier_text_uses_env_key(monkeypatch):
    monkeypatch.setenv("ELSEVIER_API_KEY", "from-env")
    payload = _elsevier_payload("body")
    with patch(
        "aec_intel_agent.full_text.requests.get", return_value=_resp(200, payload)
    ) as mock_get:
        full_text.fetch_elsevier_text("10.1016/j.x")
    assert mock_get.call_args.kwargs["headers"]["X-ELS-APIKey"] == "from-env"


# ---------------------------------------------------------------------------
# process_item integration
# ---------------------------------------------------------------------------


def test_process_item_uses_elsevier_for_10_1016_doi(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ELSEVIER_API_KEY", "fake")
    item = _crossref_item("10.1016/j.aei.2026.104619")

    with patch(
        "aec_intel_agent.full_text.requests.get",
        return_value=_resp(200, _elsevier_payload("Long Elsevier body " * 50)),
    ):
        result = full_text.process_item(item, debug_dir=tmp_path)

    assert result.full_text_status == full_text.STATUS_FULL_TEXT_EXTRACTED
    assert result.full_text_url == "https://doi.org/10.1016/j.aei.2026.104619"
    # Debug file was written.
    assert result.full_text_path and Path(result.full_text_path).exists()


def test_process_item_skips_elsevier_for_non_elsevier_doi(monkeypatch):
    """For a Springer DOI, Elsevier path should not even be tried."""
    monkeypatch.setenv("ELSEVIER_API_KEY", "fake")
    item = _crossref_item("10.1007/s00000-000-0000-0")  # Springer

    # No arxiv URL, no .pdf URL, no Unpaywall match → LOGIN_REQUIRED.
    with patch(
        "aec_intel_agent.full_text.unpaywall_lookup", return_value=None
    ), patch(
        "aec_intel_agent.full_text.requests.get",
        side_effect=AssertionError("Elsevier API must not be called"),
    ):
        result = full_text.process_item(item)
    assert result.full_text_status == full_text.STATUS_LOGIN_REQUIRED


def test_process_item_falls_back_to_pdf_when_elsevier_fails(
    monkeypatch, tmp_path: Path
) -> None:
    """If Elsevier returns 404, the PDF path should still get a chance."""
    monkeypatch.setenv("ELSEVIER_API_KEY", "fake")
    item = _crossref_item("10.1016/j.unknown.000")

    # Elsevier 404, Unpaywall also misses → LOGIN_REQUIRED.
    with patch(
        "aec_intel_agent.full_text.requests.get", return_value=_resp(404)
    ), patch(
        "aec_intel_agent.full_text.unpaywall_lookup", return_value=None
    ):
        result = full_text.process_item(item)
    assert result.full_text_status == full_text.STATUS_LOGIN_REQUIRED


def test_process_item_respects_max_chars_for_elsevier_text(monkeypatch, tmp_path):
    monkeypatch.setenv("ELSEVIER_API_KEY", "fake")
    item = _crossref_item("10.1016/j.huge.000")

    big_text = "Z" * 200_000
    with patch(
        "aec_intel_agent.full_text.requests.get",
        return_value=_resp(200, _elsevier_payload(big_text)),
    ):
        result = full_text.process_item(item, debug_dir=tmp_path, max_chars=1000)

    assert result.full_text_status == full_text.STATUS_FULL_TEXT_EXTRACTED
    written = Path(result.full_text_path).read_text(encoding="utf-8")
    assert len(written) == 1000
