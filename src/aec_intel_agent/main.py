"""CLI entry point for the AEC intelligence briefing pipeline."""

from __future__ import annotations

import logging
from pathlib import Path

from aec_intel_agent.briefing import write_markdown_briefing
from aec_intel_agent.collectors.arxiv import ArxivCollector
from aec_intel_agent.collectors.crossref import CrossrefCollector
from aec_intel_agent.config_loader import load_config
from aec_intel_agent.deduplication import deduplicate_items
from aec_intel_agent.scoring import score_items

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_DIR = PROJECT_ROOT / "config"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs"


def build_briefing(
    config_dir: Path | str | None = None,
    output_dir: Path | str | None = None,
) -> Path:
    config_dir = config_dir or DEFAULT_CONFIG_DIR
    output_dir = output_dir or DEFAULT_OUTPUT_DIR

    config = load_config(config_dir)
    keywords = config["keywords"]
    scoring_rules = config["scoring_rules"]

    collectors = [
        CrossrefCollector(keywords_config=keywords),
        ArxivCollector(keywords_config=keywords),
    ]

    collected = []
    for collector in collectors:
        logger.info("Running %s collector…", collector.name)
        try:
            items = collector.collect()
            logger.info("  %s returned %d items", collector.name, len(items))
            collected.extend(items)
        except Exception as exc:
            logger.error("Collector %s failed: %s", collector.name, exc)

    unique = deduplicate_items(collected)
    logger.info("After deduplication: %d items", len(unique))

    scored = score_items(unique, keywords, scoring_rules)
    min_score = int(scoring_rules.get("minimum_score", 1))
    filtered = [item for item in scored if item.score >= min_score]

    return write_markdown_briefing(filtered, output_dir=output_dir)


def main() -> None:
    output_path = build_briefing()
    print(f"Wrote briefing: {output_path}")


if __name__ == "__main__":
    main()
