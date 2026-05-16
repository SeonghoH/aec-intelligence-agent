"""Load YAML configuration files for the MVP."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file and return an empty dict for empty files."""

    with path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def load_config(config_dir: Path | str = "config") -> dict[str, dict[str, Any]]:
    """Load all MVP configuration files."""

    base_path = Path(config_dir)
    return {
        "sources": load_yaml(base_path / "sources.yaml"),
        "keywords": load_yaml(base_path / "keywords.yaml"),
        "scoring_rules": load_yaml(base_path / "scoring_rules.yaml"),
    }

