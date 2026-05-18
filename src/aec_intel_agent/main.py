"""CLI entry point for the AEC intelligence briefing pipeline."""

from __future__ import annotations

import logging
from pathlib import Path

# Load .env file when running locally (no-op in CI where secrets are injected
# as real environment variables, and no-op if python-dotenv is not installed).
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from aec_intel_agent.briefing import write_markdown_briefing
from aec_intel_agent.collectors.arxiv import ArxivCollector
from aec_intel_agent.collectors.crossref import CrossrefCollector
from aec_intel_agent.config_loader import load_config
from aec_intel_agent.deduplication import deduplicate_items
from aec_intel_agent.full_text import process_items as run_full_text_pipeline
from aec_intel_agent.llm_summarizer import process_items as run_llm_summarizer
from aec_intel_agent.notion_client import update_research_item_summary, upload_to_notion
from aec_intel_agent.scoring import score_items
from aec_intel_agent.seen_items import (
    DEFAULT_SEEN_PATH,
    filter_unseen,
    load_seen,
    mark_seen,
    save_seen,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_DIR = PROJECT_ROOT / "config"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs"
DEFAULT_FULL_TEXT_DIR = PROJECT_ROOT / "data" / "full_text"
DEFAULT_SEEN_ITEMS_PATH = PROJECT_ROOT / DEFAULT_SEEN_PATH


def _log_score_distribution(scored_items: list) -> None:
    """Log a simple histogram and the top 10 items by score."""
    total = len(scored_items)
    buckets = {"≥80": 0, "70-79": 0, "30-69": 0, "<30": 0}
    for item in scored_items:
        s = item.score
        if s >= 80:
            buckets["≥80"] += 1
        elif s >= 70:
            buckets["70-79"] += 1
        elif s >= 30:
            buckets["30-69"] += 1
        else:
            buckets["<30"] += 1

    logger.info(
        "Score distribution (total=%d): ≥80=%d, 70-79=%d, 30-69=%d, <30=%d",
        total, buckets["≥80"], buckets["70-79"], buckets["30-69"], buckets["<30"],
    )

    top = sorted(scored_items, key=lambda i: i.score, reverse=True)[:10]
    if top:
        logger.info("Top %d items by score:", len(top))
        for idx, item in enumerate(top, 1):
            topics = ",".join(item.topics) if item.topics else "-"
            title = (item.title or "")[:80]
            logger.info("  %2d. [%3d] [%s] %s", idx, item.score, topics, title)


def build_briefing(
    config_dir: Path | str | None = None,
    output_dir: Path | str | None = None,
    seen_items_path: Path | str | None = None,
) -> Path:
    config_dir = config_dir or DEFAULT_CONFIG_DIR
    output_dir = output_dir or DEFAULT_OUTPUT_DIR
    seen_path = Path(seen_items_path) if seen_items_path else DEFAULT_SEEN_ITEMS_PATH

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
    _log_score_distribution(scored)
    min_score = int(scoring_rules.get("minimum_score", 1))
    filtered = [item for item in scored if item.score >= min_score]

    # Exclude items already shown in previous briefings. The seen-key set is
    # persisted in `data/seen_items.json` and committed by the workflow.
    seen = load_seen(seen_path)
    fresh, repeats = filter_unseen(filtered, seen)
    logger.info(
        "Seen-item filter: %d fresh, %d already-seen (excluded).",
        len(fresh),
        len(repeats),
    )

    # Optional full-text discovery for the highest-scoring candidates.
    # Errors are swallowed inside the module — never blocks downstream steps.
    try:
        fresh = run_full_text_pipeline(fresh, debug_dir=DEFAULT_FULL_TEXT_DIR)
    except Exception as exc:
        logger.warning("Full-text pipeline raised unexpectedly: %s", exc)

    # Optional LLM summarization. Disabled unless LLM_ENABLED=true and an
    # API key is set. Attaches `metadata["llm_summary"]` to processed items.
    try:
        fresh = run_llm_summarizer(fresh)
    except Exception as exc:
        logger.warning("LLM summarizer raised unexpectedly: %s", exc)

    output_path = write_markdown_briefing(
        fresh,
        output_dir=output_dir,
        total_collected=len(collected),
    )

    upload_to_notion(
        briefing_path=output_path,
        items=fresh,
        total_collected=len(collected),
    )

    # Push LLM summaries back to the corresponding Notion Research Items
    # pages. Safe no-op when Notion is not configured or pages are missing.
    for item in fresh:
        meta = item.metadata if isinstance(item.metadata, dict) else {}
        summary = meta.get("llm_summary") if isinstance(meta, dict) else None
        if not summary:
            continue
        try:
            update_research_item_summary(item, summary)
        except Exception as exc:
            logger.warning(
                "Notion LLM summary update raised unexpectedly: %s", exc
            )

    # Persist the updated seen-key set only after a successful run.
    try:
        save_seen(mark_seen(fresh, seen), seen_path)
    except Exception as exc:
        logger.warning("Could not persist seen-items file: %s", exc)

    return output_path


def main() -> None:
    output_path = build_briefing()
    print(f"Wrote briefing: {output_path}")


if __name__ == "__main__":
    main()
