# AEC Intelligence Agent

Initial MVP skeleton for a Python-based AEC intelligence agent.

The future agent will collect daily papers and news about BIM, openBIM, digital architecture, construction technology, digital twins, AI in construction, structural steel, steel construction, and LCA / embodied carbon.

This MVP only includes:

- A `StandardItem` Pydantic model
- Placeholder collectors
- Config-driven keyword scoring
- DOI and URL deduplication
- Markdown briefing generation
- Basic tests

It does not include a dashboard, Notion integration, email, vector database, frontend UI, or multi-agent logic.

## Requirements

- Python 3.11+

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Run The MVP

```bash
aec-intel-agent
```

Or, without installing the console script:

```bash
PYTHONPATH=src python -m aec_intel_agent.main
```

The command writes a Markdown briefing to `outputs/`.

## Run Tests

```bash
pytest
```

