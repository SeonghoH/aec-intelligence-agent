"""Open-access full-text discovery and temporary extraction.

This module:

- Selects a small number of high-relevance candidates.
- Detects an open-access PDF URL (arXiv or direct ``.pdf`` links only).
- Downloads the PDF with a timeout and a size cap, never persisting it.
- Extracts text page-by-page, capped at ``FULL_TEXT_MAX_CHARS`` chars.
- Updates ``StandardItem.full_text_status`` (and ``_url`` / ``_path``).

It deliberately does NOT:

- Bypass paywalls, logins, or rate limits.
- Use browser automation or cookies.
- Persist PDF files (only extracted text, and only under
  ``data/full_text/`` which is gitignored).
- Upload extracted full text to Notion or as a workflow artifact.
- Summarize with an LLM (separate, future concern).
"""

from __future__ import annotations

import io
import logging
import os
import re
from pathlib import Path
from typing import Any

import pypdf
import requests

from aec_intel_agent.models import StandardItem

logger = logging.getLogger(__name__)

# --- Status constants -------------------------------------------------------

STATUS_NOT_ATTEMPTED = "Not Attempted"
STATUS_METADATA_ONLY = "Metadata Only"
STATUS_ABSTRACT_ONLY = "Abstract Only"
STATUS_OA_PDF_FOUND = "Open Access PDF Found"
STATUS_FULL_TEXT_EXTRACTED = "Full Text Extracted"
STATUS_DOWNLOAD_FAILED = "PDF Download Failed"
STATUS_EXTRACTION_FAILED = "PDF Text Extraction Failed"
STATUS_LOGIN_REQUIRED = "Login Required / Skipped"

ALL_STATUSES = (
    STATUS_NOT_ATTEMPTED,
    STATUS_METADATA_ONLY,
    STATUS_ABSTRACT_ONLY,
    STATUS_OA_PDF_FOUND,
    STATUS_FULL_TEXT_EXTRACTED,
    STATUS_DOWNLOAD_FAILED,
    STATUS_EXTRACTION_FAILED,
    STATUS_LOGIN_REQUIRED,
)

# --- Configuration ----------------------------------------------------------

DEFAULT_MAX_ITEMS = 3
DEFAULT_MAX_CHARS = 60000
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_MAX_PDF_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB

CANDIDATE_SCORE_THRESHOLD = 80
CANDIDATE_SOURCE_TYPES = {"paper", "preprint"}

# Unpaywall — free DOI → open-access PDF lookup. The API REQUIRES an
# email parameter so they can contact heavy users; the default below is
# a generic identifier. Override via the `UNPAYWALL_EMAIL` env var.
UNPAYWALL_API_BASE = "https://api.unpaywall.org/v2"
UNPAYWALL_DEFAULT_EMAIL = "aec-intelligence-agent@example.com"
UNPAYWALL_TIMEOUT_SECONDS = 10

_ARXIV_ID_PATTERN = re.compile(
    r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5}(?:v\d+)?)", re.IGNORECASE
)
_FILENAME_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _get_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = int(raw)
        return value if value >= 0 else default
    except (ValueError, TypeError):
        return default


def get_max_items() -> int:
    return _get_int_env("FULL_TEXT_MAX_ITEMS", DEFAULT_MAX_ITEMS)


def get_max_chars() -> int:
    return _get_int_env("FULL_TEXT_MAX_CHARS", DEFAULT_MAX_CHARS)


# --- Candidate selection ----------------------------------------------------


def _source_type(item: StandardItem) -> str:
    metadata = item.metadata if isinstance(item.metadata, dict) else {}
    return str(metadata.get("source_type") or item.item_type or "").lower()


def select_candidates(
    items: list[StandardItem], max_items: int | None = None
) -> list[StandardItem]:
    """Return items eligible for full-text fetching.

    Eligibility: ``score >= 80`` and ``source_type`` is ``paper`` or
    ``preprint``. Order is preserved (caller is expected to pass items
    sorted by descending relevance). Capped at ``max_items`` (default
    from ``FULL_TEXT_MAX_ITEMS`` env var).
    """
    limit = max_items if max_items is not None else get_max_items()
    if limit <= 0:
        return []

    selected: list[StandardItem] = []
    for item in items:
        if item.score < CANDIDATE_SCORE_THRESHOLD:
            continue
        if _source_type(item) not in CANDIDATE_SOURCE_TYPES:
            continue
        selected.append(item)
        if len(selected) >= limit:
            break
    return selected


# --- PDF URL detection ------------------------------------------------------


def unpaywall_lookup(
    doi: str, *, email: str | None = None
) -> str | None:
    """Query Unpaywall for an open-access PDF URL given a DOI.

    Returns the best OA PDF URL, or ``None`` if the DOI is unknown,
    closed-access, or the request fails. Never raises — every error
    path turns into ``None`` so the caller can keep using its
    "no PDF" fallback.
    """
    doi_clean = (doi or "").strip()
    if not doi_clean:
        return None
    doi_clean = doi_clean.removeprefix("https://doi.org/").removeprefix("doi:")

    address = (email or os.environ.get("UNPAYWALL_EMAIL")
               or UNPAYWALL_DEFAULT_EMAIL).strip()

    try:
        response = requests.get(
            f"{UNPAYWALL_API_BASE}/{doi_clean}",
            params={"email": address},
            timeout=UNPAYWALL_TIMEOUT_SECONDS,
            headers={"User-Agent": f"aec-intelligence-agent (+{address})"},
        )
    except Exception as exc:
        logger.info("Unpaywall: lookup failed for %s: %s", doi_clean, exc)
        return None

    if response.status_code != 200:
        # 404 (DOI unknown) is normal and not worth a warning.
        if response.status_code != 404:
            logger.info(
                "Unpaywall: HTTP %d for %s", response.status_code, doi_clean
            )
        return None

    try:
        data = response.json()
    except Exception:
        return None

    if not isinstance(data, dict) or not data.get("is_oa"):
        return None

    best = data.get("best_oa_location")
    if not isinstance(best, dict):
        return None

    pdf_url = best.get("url_for_pdf") or best.get("url")
    if pdf_url:
        return str(pdf_url)
    return None


def detect_pdf_url(item: StandardItem) -> str | None:
    """Detect an open-access PDF URL, or return ``None``.

    Three safe paths, in order:

    1. arXiv abs URL → ``https://arxiv.org/pdf/{id}.pdf``
    2. Direct ``.pdf`` URL → returned as-is
    3. DOI → Unpaywall best OA location (if any)

    Anything else (paywalled publisher pages with no OA mirror) returns
    ``None`` and the item is left at ``STATUS_LOGIN_REQUIRED``.
    """
    url = (item.url or "").strip()

    # 1. arXiv
    if url and (
        (item.source or "").lower() == "arxiv" or "arxiv.org/" in url.lower()
    ):
        match = _ARXIV_ID_PATTERN.search(url)
        if match:
            arxiv_id = re.sub(r"v\d+$", "", match.group(1))
            return f"https://arxiv.org/pdf/{arxiv_id}.pdf"

    # 2. Direct PDF link
    if url and url.lower().endswith(".pdf"):
        return url

    # 3. DOI → Unpaywall (catches Crossref papers with author-deposited OA)
    if item.doi:
        oa_url = unpaywall_lookup(item.doi)
        if oa_url:
            logger.info(
                "Unpaywall: found OA PDF for %s", item.doi
            )
            return oa_url

    return None


# --- Download + extract -----------------------------------------------------


def download_pdf(
    url: str,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    max_size: int = DEFAULT_MAX_PDF_SIZE_BYTES,
) -> bytes:
    """Download a PDF with a timeout and a size cap.

    Raises ``ValueError`` if the response is HTML (likely a paywall page)
    or the body exceeds ``max_size``. Re-raises any ``requests`` error.
    """
    response = requests.get(
        url,
        timeout=timeout,
        stream=True,
        headers={"User-Agent": "aec-intelligence-agent/0.1 (research tool)"},
        allow_redirects=True,
    )
    response.raise_for_status()

    content_type = response.headers.get("Content-Type", "").lower()
    if "html" in content_type:
        raise ValueError(
            f"Received HTML response instead of PDF (likely paywall): {content_type!r}"
        )

    total = 0
    chunks: list[bytes] = []
    for chunk in response.iter_content(chunk_size=8192):
        if not chunk:
            continue
        total += len(chunk)
        if total > max_size:
            raise ValueError(f"PDF size {total} exceeds max {max_size} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


def extract_text(pdf_bytes: bytes, max_chars: int | None = None) -> str:
    """Extract text from a PDF byte string, capped at ``max_chars``."""
    limit = max_chars if max_chars is not None else get_max_chars()
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))

    parts: list[str] = []
    total = 0
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        if not text:
            continue
        remaining = limit - total
        if remaining <= 0:
            break
        if len(text) > remaining:
            parts.append(text[:remaining])
            break
        parts.append(text)
        total += len(text)
    # Final hard cap — the page separator can push us one char over otherwise.
    return "\n".join(parts)[:limit]


# --- Item-level processing --------------------------------------------------


def _safe_filename(item: StandardItem) -> str:
    base = (item.doi or item.title or "item").strip()
    base = _FILENAME_SAFE.sub("_", base)
    return (base or "item")[:100]


def _with_status(
    item: StandardItem,
    status: str,
    *,
    full_text_url: str | None = None,
    full_text_path: str | None = None,
) -> StandardItem:
    updates: dict[str, Any] = {"full_text_status": status}
    if full_text_url is not None:
        updates["full_text_url"] = full_text_url
    if full_text_path is not None:
        updates["full_text_path"] = full_text_path
    if hasattr(item, "model_copy"):
        return item.model_copy(update=updates)
    return item.copy(update=updates)


def process_item(
    item: StandardItem,
    debug_dir: Path | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    max_chars: int | None = None,
) -> StandardItem:
    """Run the full-text pipeline for one item. Never raises."""
    pdf_url = detect_pdf_url(item)
    if pdf_url is None:
        return _with_status(item, STATUS_LOGIN_REQUIRED)

    try:
        pdf_bytes = download_pdf(pdf_url, timeout=timeout)
    except Exception as exc:
        logger.warning(
            "Full-text: download failed for %r: %s", (item.title or "")[:60], exc
        )
        return _with_status(item, STATUS_DOWNLOAD_FAILED, full_text_url=pdf_url)

    try:
        text = extract_text(pdf_bytes, max_chars=max_chars)
    except Exception as exc:
        logger.warning(
            "Full-text: extraction failed for %r: %s", (item.title or "")[:60], exc
        )
        return _with_status(item, STATUS_EXTRACTION_FAILED, full_text_url=pdf_url)

    if not text.strip():
        return _with_status(item, STATUS_EXTRACTION_FAILED, full_text_url=pdf_url)

    debug_path: str | None = None
    if debug_dir is not None:
        try:
            debug_dir.mkdir(parents=True, exist_ok=True)
            target = debug_dir / f"{_safe_filename(item)}.txt"
            target.write_text(text, encoding="utf-8")
            debug_path = str(target)
        except Exception as exc:
            logger.warning("Full-text: failed to write debug file: %s", exc)

    return _with_status(
        item,
        STATUS_FULL_TEXT_EXTRACTED,
        full_text_url=pdf_url,
        full_text_path=debug_path,
    )


def process_items(
    items: list[StandardItem],
    debug_dir: Path | None = None,
) -> list[StandardItem]:
    """Process a small subset of high-relevance candidates.

    Returns a new list with full_text fields updated on candidates. Items
    that are not candidates are passed through unchanged.
    """
    candidates = select_candidates(items)
    if not candidates:
        return list(items)

    candidate_ids = {id(c) for c in candidates}
    logger.info(
        "Full-text: processing %d of %d candidate(s).", len(candidates), len(items)
    )

    out: list[StandardItem] = []
    for item in items:
        if id(item) in candidate_ids:
            try:
                out.append(process_item(item, debug_dir=debug_dir))
            except Exception as exc:
                # process_item should never raise — this is a final safety net.
                logger.warning(
                    "Full-text: unexpected failure for %r: %s",
                    (item.title or "")[:60],
                    exc,
                )
                out.append(item)
        else:
            out.append(item)
    return out
