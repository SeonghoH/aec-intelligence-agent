"""arXiv API collector."""

from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from typing import Any

import requests

from aec_intel_agent.collectors.base import BaseCollector
from aec_intel_agent.models import StandardItem

logger = logging.getLogger(__name__)

ARXIV_API_URL = "http://export.arxiv.org/api/query"
MAX_RESULTS_PER_QUERY = 15  # Fetch more to account for date filtering
DAYS_LOOKBACK = 3
INTER_QUERY_DELAY_SECONDS = 3.0  # arXiv asks ~3s between requests; avoids 429s.
_ATOM = "http://www.w3.org/2005/Atom"


class ArxivCollector(BaseCollector):
    """Collect recent preprints from the arXiv Atom API."""

    name = "arxiv"

    def collect(self) -> list[StandardItem]:
        items: list[StandardItem] = []
        seen_ids: set[str] = set()

        topic_values = [
            kws for kws in self.keywords_config.get("topics", {}).values() if kws
        ]
        for idx, topic_keywords in enumerate(topic_values):
            keyword = topic_keywords[0]
            # arXiv's API enforces a rate limit; pause between queries.
            if idx > 0 and INTER_QUERY_DELAY_SECONDS > 0:
                time.sleep(INTER_QUERY_DELAY_SECONDS)
            try:
                fetched = self._fetch(keyword, seen_ids)
                items.extend(fetched)
            except Exception as exc:
                logger.warning("arXiv query failed for %r: %s", keyword, exc)

        return items

    def _fetch(self, query: str, seen_ids: set[str]) -> list[StandardItem]:
        cutoff = date.today() - timedelta(days=DAYS_LOOKBACK)
        params: dict[str, Any] = {
            "search_query": f"all:{query}",
            "max_results": MAX_RESULTS_PER_QUERY,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        # arXiv started rejecting requests without a User-Agent (HTTP 406).
        # Also set Accept explicitly to the Atom feed format the API serves.
        headers = {
            "User-Agent": "aec-intelligence-agent/0.1 (research; +https://github.com)",
            "Accept": "application/atom+xml, application/xml;q=0.9, */*;q=0.5",
        }
        response = requests.get(
            ARXIV_API_URL, params=params, headers=headers, timeout=15
        )
        response.raise_for_status()
        return _parse_feed(response.text, seen_ids, cutoff=cutoff)


def _parse_feed(
    xml_text: str, seen_ids: set[str], cutoff: date | None = None
) -> list[StandardItem]:
    root = ET.fromstring(xml_text)
    items = []
    for entry in root.findall(f"{{{_ATOM}}}entry"):
        item = _parse_entry(entry, seen_ids, cutoff=cutoff)
        if item:
            items.append(item)
    return items


def _parse_entry(
    entry: ET.Element, seen_ids: set[str], cutoff: date | None = None
) -> StandardItem | None:
    id_elem = entry.find(f"{{{_ATOM}}}id")
    arxiv_id = (id_elem.text or "").strip() if id_elem is not None else ""
    if not arxiv_id or arxiv_id in seen_ids:
        return None
    seen_ids.add(arxiv_id)

    title_elem = entry.find(f"{{{_ATOM}}}title")
    title = " ".join((title_elem.text or "").split()) if title_elem is not None else ""
    if not title:
        return None

    summary_elem = entry.find(f"{{{_ATOM}}}summary")
    summary = " ".join((summary_elem.text or "").split()) if summary_elem is not None else ""

    pub_date: date | None = None
    published_elem = entry.find(f"{{{_ATOM}}}published")
    if published_elem is not None and published_elem.text:
        try:
            pub_date = date.fromisoformat(published_elem.text[:10])
        except ValueError:
            pass

    # Skip entries older than the cutoff date.
    if cutoff is not None and pub_date is not None and pub_date < cutoff:
        return None

    authors = []
    for author_elem in entry.findall(f"{{{_ATOM}}}author"):
        name_elem = author_elem.find(f"{{{_ATOM}}}name")
        if name_elem is not None and name_elem.text:
            authors.append(name_elem.text.strip())

    raw = {
        "id": arxiv_id,
        "title": title,
        "summary": summary,
        "published": published_elem.text if published_elem is not None else None,
        "authors": list(authors),
    }
    return StandardItem(
        title=title,
        source="arxiv",
        url=arxiv_id,
        item_type="preprint",
        published_date=pub_date,
        authors=authors,
        summary=summary[:600],
        metadata={
            "source_type": "preprint",
            "raw": raw,
        },
    )
