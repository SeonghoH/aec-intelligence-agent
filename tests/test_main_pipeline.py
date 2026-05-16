"""End-to-end tests for the main pipeline with mocked collectors."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

from aec_intel_agent.main import build_briefing
from aec_intel_agent.models import StandardItem


def _crossref_sample() -> list[StandardItem]:
    return [
        StandardItem(
            title="openBIM workflows for structural steel monitoring",
            source="crossref",
            url="https://doi.org/10.1234/openbim-steel",
            doi="10.1234/openbim-steel",
            item_type="paper",
            published_date=date(2026, 4, 30),
            authors=["Alice"],
            summary="A study on openBIM, IFC, and steel construction monitoring.",
            metadata={"source_type": "paper", "raw": {"DOI": "10.1234/openbim-steel"}},
        )
    ]


def _arxiv_sample() -> list[StandardItem]:
    return [
        StandardItem(
            title="Digital twin for BIM models",
            source="arxiv",
            url="http://arxiv.org/abs/2501.99999v1",
            item_type="preprint",
            published_date=date(2026, 5, 1),
            authors=["Bob"],
            summary="A digital twin approach for BIM-based monitoring.",
            metadata={"source_type": "preprint", "raw": {"id": "2501.99999"}},
        )
    ]


@patch("aec_intel_agent.main.ArxivCollector.collect")
@patch("aec_intel_agent.main.CrossrefCollector.collect")
def test_pipeline_writes_briefing_when_both_collectors_work(
    mock_crossref, mock_arxiv, tmp_path
):
    mock_crossref.return_value = _crossref_sample()
    mock_arxiv.return_value = _arxiv_sample()

    output_path = build_briefing(config_dir="config", output_dir=str(tmp_path))

    assert output_path.exists()
    content = output_path.read_text(encoding="utf-8")
    assert "openBIM workflows for structural steel monitoring" in content
    assert "Digital twin for BIM models" in content


@patch(
    "aec_intel_agent.main.ArxivCollector.collect",
    side_effect=RuntimeError("arxiv api down"),
)
@patch("aec_intel_agent.main.CrossrefCollector.collect")
def test_pipeline_continues_when_arxiv_fails(mock_crossref, mock_arxiv, tmp_path):
    mock_crossref.return_value = _crossref_sample()

    output_path = build_briefing(config_dir="config", output_dir=str(tmp_path))

    assert output_path.exists()
    content = output_path.read_text(encoding="utf-8")
    # Crossref item should still be present.
    assert "openBIM workflows for structural steel monitoring" in content


@patch("aec_intel_agent.main.ArxivCollector.collect")
@patch(
    "aec_intel_agent.main.CrossrefCollector.collect",
    side_effect=RuntimeError("crossref api down"),
)
def test_pipeline_continues_when_crossref_fails(mock_crossref, mock_arxiv, tmp_path):
    mock_arxiv.return_value = _arxiv_sample()

    output_path = build_briefing(config_dir="config", output_dir=str(tmp_path))

    assert output_path.exists()
    content = output_path.read_text(encoding="utf-8")
    assert "Digital twin for BIM models" in content


@patch(
    "aec_intel_agent.main.ArxivCollector.collect",
    side_effect=RuntimeError("arxiv api down"),
)
@patch(
    "aec_intel_agent.main.CrossrefCollector.collect",
    side_effect=RuntimeError("crossref api down"),
)
def test_pipeline_still_writes_briefing_when_both_collectors_fail(
    mock_crossref, mock_arxiv, tmp_path
):
    output_path = build_briefing(config_dir="config", output_dir=str(tmp_path))

    assert output_path.exists()
    content = output_path.read_text(encoding="utf-8")
    # File exists with the empty-section fallback text.
    assert "해당 항목 없음" in content
