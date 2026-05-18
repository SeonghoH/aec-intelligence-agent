"""Crossref REST API collector."""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Any

import requests

from aec_intel_agent.collectors.base import BaseCollector
from aec_intel_agent.models import StandardItem

logger = logging.getLogger(__name__)

CROSSREF_API_URL = "https://api.crossref.org/works"
DAYS_LOOKBACK = 3
MAX_ROWS_PER_QUERY = 10
_JATS_TAG = re.compile(r"<[^>]+>")


class CrossrefCollector(BaseCollector):
    """Collect recent papers from the Crossref REST API."""

    name = "crossref"

    def collect(self) -> list[StandardItem]:
        since_date = (date.today() - timedelta(days=DAYS_LOOKBACK)).isoformat()
        items: list[StandardItem] = []
        seen_dois: set[str] = set()

        for topic_keywords in self.keywords_config.get("topics", {}).values():
            if not topic_keywords:
                continue
            keyword = topic_keywords[0]
            try:
                fetched = self._fetch(keyword, since_date, seen_dois)
                items.extend(fetched)
            except Exception as exc:
                logger.warning("Crossref query failed for %r: %s", keyword, exc)

        return items

    def _fetch(
        self, query: str, since_date: str, seen_dois: set[str]
    ) -> list[StandardItem]:
        params: dict[str, Any] = {
            "query": query,
            "rows": MAX_ROWS_PER_QUERY,
            "sort": "published",
            "order": "desc",
            "filter": f"from-pub-date:{since_date}",
            "select": "DOI,title,URL,abstract,published,author,type",
        }
        response = requests.get(
            CROSSREF_API_URL,
            params=params,
            timeout=15,
            headers={"User-Agent": "aec-intelligence-agent/0.1 (research tool)"},
        )
        response.raise_for_status()
        works = response.json().get("message", {}).get("items", [])

        result = []
        for work in works:
            doi = (work.get("DOI") or "").strip().lower()
            if doi and doi in seen_dois:
                continue
            item = self._parse_work(work)
            if item:
                if doi:
                    seen_dois.add(doi)
                result.append(item)
        return result

    def _parse_work(self, work: dict[str, Any]) -> StandardItem | None:
        titles = work.get("title") or []
        title = titles[0].strip() if titles else ""
        if not title:
            return None

        doi = (work.get("DOI") or "").strip() or None
        url = work.get("URL") or (f"https://doi.org/{doi}" if doi else None)

        raw_abstract = work.get("abstract") or ""
        abstract = _JATS_TAG.sub(" ", raw_abstract).strip()
        abstract = " ".join(abstract.split())

        pub_date = _parse_crossref_date(work)

        authors = [
            _format_author(a)
            for a in work.get("author", [])
            if _format_author(a)
        ]

        return StandardItem(
            title=title,
            source=self.name,
            url=url,
            doi=doi,
            item_type="paper",
            published_date=pub_date,
            authors=authors,
            summary=abstract[:600],
            metadata={
                "source_type": "paper",
                "raw": work,
            },
        )


def _parse_crossref_date(work: dict[str, Any]) -> date | None:
    for key in ("published", "published-print", "published-online"):
        blob = work.get(key)
        if not blob:
            continue
        parts_list = blob.get("date-parts") or []
        parts = parts_list[0] if parts_list else []
        try:
            if len(parts) >= 3:
                return date(parts[0], parts[1], parts[2])
            if len(parts) == 2:
                return date(parts[0], parts[1], 1)
            if len(parts) == 1:
                return date(parts[0], 1, 1)
        except (ValueError, TypeError):
            pass
    return None


def _format_author(author: dict[str, Any]) -> str:
    given = (author.get("given") or "").strip()
    family = (author.get("family") or "").strip()
    if given and family:
        return f"{given} {family}"
    return family or given
