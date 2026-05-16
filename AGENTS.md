# Agent Notes

This repository is intentionally small and conservative.

## Current Scope

- Keep the MVP Python-only.
- Use Pydantic for shared data models.
- Keep collectors simple and replaceable.
- Use readable, explicit code over clever abstractions.
- Keep config in YAML files under `config/`.

## Do Not Add Yet

- Dashboard or frontend UI
- Notion integration
- Email delivery
- Vector database
- Multi-agent workflow
- Production scheduler

## Development Rules

- Target Python 3.11+.
- Prefer small modules with clear responsibilities.
- Add tests when changing scoring, deduplication, models, or briefing output.
- Keep generated data out of version control.

