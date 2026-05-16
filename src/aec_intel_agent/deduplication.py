"""Deduplicate normalized items."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from aec_intel_agent.models import StandardItem


def normalize_doi(doi: str | None) -> str | None:
    """Normalize DOI strings for comparison."""

    if not doi:
        return None

    normalized = doi.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if normalized.startswith(prefix):
            normalized = normalized.removeprefix(prefix)
    return normalized.strip() or None


def normalize_url(url: str | None) -> str | None:
    """Normalize URLs enough for simple duplicate detection."""

    if not url:
        return None

    parts = urlsplit(url.strip())
    scheme = (parts.scheme or "https").lower()
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/")
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
    ]
    query = urlencode(sorted(query_pairs))
    return urlunsplit((scheme, netloc, path, query, ""))


def deduplicate_items(items: list[StandardItem]) -> list[StandardItem]:
    """Remove items with duplicate DOI or duplicate URL."""

    seen_dois: set[str] = set()
    seen_urls: set[str] = set()
    unique_items: list[StandardItem] = []

    for item in items:
        doi = normalize_doi(item.doi)
        url = normalize_url(item.url)

        if doi and doi in seen_dois:
            continue
        if url and url in seen_urls:
            continue

        unique_items.append(item)
        if doi:
            seen_dois.add(doi)
        if url:
            seen_urls.add(url)

    return unique_items

