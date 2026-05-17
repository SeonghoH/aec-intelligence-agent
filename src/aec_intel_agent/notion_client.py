"""Optional Notion upload integration.

The pipeline calls `upload_to_notion()` after the Markdown briefing is written.
If any required environment variable is missing, the upload is skipped silently
so the pipeline can keep running. All Notion failures are logged and swallowed:
they never block the Markdown briefing.
"""

from __future__ import annotations

import logging
import os
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

import requests

from aec_intel_agent.deduplication import (
    normalize_doi,
    normalize_title,
    normalize_url,
)
from aec_intel_agent.models import StandardItem

logger = logging.getLogger(__name__)

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
REQUEST_TIMEOUT_SECONDS = 30
RICH_TEXT_CHUNK_SIZE = 2000
MAX_RICH_TEXT_CHUNKS = 5
MAX_MULTI_SELECT = 50

_STEEL_TOPICS = {"structural_steel", "steel_construction"}
_LCA_TOPICS = {"embodied_carbon"}
_BIM_TOPICS = {
    "bim",
    "openbim",
    "digital_architecture",
    "construction_technology",
    "digital_twin",
    "ai_in_construction",
}

MUST_READ_THRESHOLD = 10
SAVE_THRESHOLD = 5


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def is_configured() -> bool:
    return all(
        os.environ.get(var)
        for var in ("NOTION_TOKEN", "NOTION_DAILY_DB_ID", "NOTION_RESEARCH_DB_ID")
    )


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# Property helpers
# ---------------------------------------------------------------------------


def _chunked_rich_text(content: Any) -> dict[str, Any]:
    if content in (None, ""):
        return {"rich_text": []}
    text = str(content)
    chunks = [
        text[i : i + RICH_TEXT_CHUNK_SIZE]
        for i in range(0, len(text), RICH_TEXT_CHUNK_SIZE)
    ][:MAX_RICH_TEXT_CHUNKS]
    return {
        "rich_text": [
            {"type": "text", "text": {"content": chunk}} for chunk in chunks
        ]
    }


def _title_prop(content: str | None) -> dict[str, Any]:
    text = (content or "").strip()[:RICH_TEXT_CHUNK_SIZE] or "(제목 없음)"
    return {"title": [{"type": "text", "text": {"content": text}}]}


def _date_prop(value: Any) -> dict[str, Any]:
    if value is None or value == "":
        return {"date": None}
    if isinstance(value, datetime):
        return {"date": {"start": value.date().isoformat()}}
    if isinstance(value, date):
        return {"date": {"start": value.isoformat()}}
    return {"date": {"start": str(value)}}


def _select_prop(name: str | None) -> dict[str, Any]:
    if not name:
        return {"select": None}
    return {"select": {"name": str(name)}}


def _multi_select_prop(values: list[str] | None) -> dict[str, Any]:
    cleaned = [str(v) for v in (values or []) if v][:MAX_MULTI_SELECT]
    return {"multi_select": [{"name": v} for v in cleaned]}


def _url_prop(value: str | None) -> dict[str, Any]:
    if not value:
        return {"url": None}
    return {"url": str(value)}


def _number_prop(value: Any) -> dict[str, Any]:
    if value is None:
        return {"number": None}
    return {"number": float(value)}


# ---------------------------------------------------------------------------
# Derived fields
# ---------------------------------------------------------------------------


def _relevance_label(item: StandardItem) -> str:
    if item.score >= MUST_READ_THRESHOLD:
        return "High"
    topics = set(item.topics or [])
    if topics & (_STEEL_TOPICS | _LCA_TOPICS | _BIM_TOPICS):
        return "High"
    if item.score >= SAVE_THRESHOLD:
        return "Medium"
    return "Low"


def _main_themes(items: list[StandardItem], top_n: int = 5) -> list[str]:
    counter: Counter[str] = Counter()
    for item in items:
        for topic in item.topics or []:
            counter[topic] += 1
    return [name for name, _ in counter.most_common(top_n)]


def _github_output_url(briefing_path: Path) -> str | None:
    repo = os.environ.get("GITHUB_REPOSITORY")
    ref = os.environ.get("GITHUB_REF_NAME", "main")
    if repo:
        return f"https://github.com/{repo}/blob/{ref}/outputs/{briefing_path.name}"
    return None


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------


def build_daily_briefing_properties(
    *,
    date_str: str,
    total_collected: int,
    included: int,
    main_themes: list[str],
    markdown: str,
    github_url: str | None,
) -> dict[str, Any]:
    return {
        "Title": _title_prop(f"Daily Briefing — {date_str}"),
        "Date": _date_prop(date_str),
        "Total Items": _number_prop(total_collected),
        "Included Items": _number_prop(included),
        "Main Themes": _multi_select_prop(main_themes),
        "Status": _select_prop("Draft"),
        "Markdown Summary": _chunked_rich_text(markdown),
        "GitHub Output Path": _url_prop(github_url),
    }


def build_research_item_properties(
    item: StandardItem,
    *,
    why_it_matters: str,
    relevance_to_seongho: str,
    summary_text: str,
) -> dict[str, Any]:
    """Build Notion properties. DOI and URL are stored normalized so that
    future duplicate-check queries use the same canonical form."""
    metadata = item.metadata if isinstance(item.metadata, dict) else {}
    source_type = metadata.get("source_type") or item.item_type or "article"

    doi_norm = normalize_doi(item.doi) or ""
    url_norm = normalize_url(item.url)

    return {
        "Title": _title_prop(item.title),
        "Published Date": _date_prop(item.published_date),
        "Source": _select_prop(item.source),
        "Source Type": _select_prop(source_type),
        "DOI": _chunked_rich_text(doi_norm),
        "URL": _url_prop(url_norm),
        "Score": _number_prop(item.score),
        "Tags": _multi_select_prop(item.topics),
        "Relevance": _select_prop(_relevance_label(item)),
        "Read Status": _select_prop("Unread"),
        "Related Work": _multi_select_prop([]),
        "Summary": _chunked_rich_text(summary_text),
        "Why It Matters": _chunked_rich_text(why_it_matters),
        "Relevance to Seongho": _chunked_rich_text(relevance_to_seongho),
        "Full-text Status": _select_prop("Not Available"),
    }


# ---------------------------------------------------------------------------
# Notion API calls
# ---------------------------------------------------------------------------


def _query_database(token: str, db_id: str, filter_obj: dict[str, Any]) -> list[dict]:
    response = requests.post(
        f"{NOTION_API_BASE}/databases/{db_id}/query",
        headers=_headers(token),
        json={"filter": filter_obj, "page_size": 1},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json().get("results", [])


def _create_page(token: str, db_id: str, properties: dict[str, Any]) -> str:
    response = requests.post(
        f"{NOTION_API_BASE}/pages",
        headers=_headers(token),
        json={"parent": {"database_id": db_id}, "properties": properties},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json().get("id", "")


def _find_existing_briefing(token: str, db_id: str, date_str: str) -> str | None:
    results = _query_database(
        token, db_id, {"property": "Date", "date": {"equals": date_str}}
    )
    return results[0]["id"] if results else None


def _find_existing_research_item(
    token: str,
    db_id: str,
    doi: str | None,
    url: str | None,
    title: str | None,
) -> str | None:
    """Look up a duplicate by DOI → URL → title (case-sensitive title match).

    All three keys are normalized before querying. Title fallback uses Notion's
    title `equals` filter, which is case-sensitive — see README for limits.
    """
    doi_norm = normalize_doi(doi)
    if doi_norm:
        results = _query_database(
            token, db_id, {"property": "DOI", "rich_text": {"equals": doi_norm}}
        )
        if results:
            return results[0]["id"]

    url_norm = normalize_url(url)
    if url_norm:
        results = _query_database(
            token, db_id, {"property": "URL", "url": {"equals": url_norm}}
        )
        if results:
            return results[0]["id"]

    title_norm = normalize_title(title)
    if title_norm:
        # Notion's API can't match against our normalized form, so we query
        # using the stripped original title. This is an exact, case-sensitive
        # comparison against the stored Title.
        results = _query_database(
            token,
            db_id,
            {"property": "Title", "title": {"equals": (title or "").strip()}},
        )
        if results:
            return results[0]["id"]

    return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def upload_to_notion(
    briefing_path: Path,
    items: list[StandardItem],
    total_collected: int,
    generated_at: datetime | None = None,
) -> dict[str, int]:
    """Upload daily briefing + research items to Notion.

    Returns counters. Skips silently when env vars are missing. Logs and
    swallows every exception so the main pipeline is never blocked.
    """
    result = {
        "daily_created": 0,
        "daily_skipped": 0,
        "items_uploaded": 0,
        "items_skipped": 0,
        "items_failed": 0,
    }

    if not is_configured():
        logger.info("Notion env vars not set — skipping Notion upload.")
        return result

    token = os.environ["NOTION_TOKEN"]
    daily_db = os.environ["NOTION_DAILY_DB_ID"]
    research_db = os.environ["NOTION_RESEARCH_DB_ID"]

    from aec_intel_agent.briefing import (
        _build_summary,
        _relevance_to_seongho,
        _why_it_matters,
    )

    timestamp = generated_at or datetime.now()
    date_str = timestamp.strftime("%Y-%m-%d")

    # ---- Daily briefing -------------------------------------------------
    try:
        existing = _find_existing_briefing(token, daily_db, date_str)
    except Exception as exc:
        logger.warning(
            "Notion: duplicate check failed for daily briefing (%s): %s",
            date_str,
            exc,
        )
        existing = None
        skip_daily_create = True  # don't risk a duplicate after a failed check
    else:
        skip_daily_create = False

    if existing:
        logger.info("Notion: daily briefing already exists for %s, skipped.", date_str)
        result["daily_skipped"] = 1
    elif not skip_daily_create:
        try:
            markdown = (
                briefing_path.read_text(encoding="utf-8")
                if briefing_path.exists()
                else ""
            )
            props = build_daily_briefing_properties(
                date_str=date_str,
                total_collected=total_collected,
                included=len(items),
                main_themes=_main_themes(items),
                markdown=markdown,
                github_url=_github_output_url(briefing_path),
            )
            _create_page(token, daily_db, props)
            result["daily_created"] = 1
            logger.info("Notion: created daily briefing for %s.", date_str)
        except Exception as exc:
            logger.warning("Notion: failed to create daily briefing: %s", exc)

    # ---- Research items -------------------------------------------------
    for item in items:
        # Step 1: duplicate check.
        try:
            existing = _find_existing_research_item(
                token, research_db, item.doi, item.url, item.title
            )
        except Exception as exc:
            logger.warning(
                "Notion: duplicate check failed for item %r: %s",
                (item.title or "")[:60],
                exc,
            )
            result["items_failed"] += 1
            continue

        if existing:
            result["items_skipped"] += 1
            continue

        # Step 2: create page.
        try:
            props = build_research_item_properties(
                item,
                why_it_matters=_why_it_matters(item),
                relevance_to_seongho=_relevance_to_seongho(item),
                summary_text=_build_summary(item),
            )
            _create_page(token, research_db, props)
            result["items_uploaded"] += 1
        except Exception as exc:
            logger.warning(
                "Notion: failed to create item %r: %s",
                (item.title or "")[:60],
                exc,
            )
            result["items_failed"] += 1

    logger.info(
        "Notion upload complete: daily_created=%d, daily_skipped=%d, "
        "items_uploaded=%d, items_skipped=%d, items_failed=%d.",
        result["daily_created"],
        result["daily_skipped"],
        result["items_uploaded"],
        result["items_skipped"],
        result["items_failed"],
    )
    return result
