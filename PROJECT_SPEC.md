# Project Spec

## Name

AEC Intelligence Agent

## Purpose

Collect, normalize, score, deduplicate, and summarize papers and news related to architecture, engineering, and construction technology.

## Initial Topics

- BIM
- openBIM
- Digital architecture
- Construction technology
- Digital twin
- AI in construction
- Structural steel
- Steel construction
- LCA / embodied carbon

## MVP Scope

The MVP provides a runnable local Python package that generates a Markdown briefing from placeholder collector data.

## MVP Components

- `StandardItem` model for normalized content
- Placeholder collectors for Crossref and arXiv
- Keyword scoring from YAML config
- Deduplication by DOI and canonical URL
- Markdown briefing writer
- Basic unit tests

## Out Of Scope For Now

- Dashboard
- Notion
- Email
- Vector database
- Frontend UI
- Multi-agent logic
- Real API collection

## Success Criteria

- `pytest` passes.
- `PYTHONPATH=src python -m aec_intel_agent.main` writes one Markdown briefing to `outputs/`.

