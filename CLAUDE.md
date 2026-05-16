# Claude Notes

This project is an MVP skeleton for an AEC intelligence agent.

Follow the same constraints as `AGENTS.md`:

- Keep implementation simple and readable.
- Do not add integrations or UI layers yet.
- Preserve the single-agent, local CLI shape.
- Prefer configuration files for source, keyword, and scoring changes.

The main runnable entry point is:

```bash
PYTHONPATH=src python -m aec_intel_agent.main
```

