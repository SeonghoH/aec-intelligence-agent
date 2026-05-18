"""Persistent "已 본 항목" 추적.

매일 브리핑을 생성할 때, 이미 이전 실행에서 본 논문은 제외한다.
저장 형식은 단순 JSON: DOI / URL / 제목을 정규화한 키 집합.

저장 위치는 `data/seen_items.json` (저장소에 커밋되어 GitHub Actions 실행 간 상태 유지).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterable

from aec_intel_agent.deduplication import (
    normalize_doi,
    normalize_title,
    normalize_url,
)
from aec_intel_agent.models import StandardItem

logger = logging.getLogger(__name__)

DEFAULT_SEEN_PATH = Path("data") / "seen_items.json"


def _item_keys(item: StandardItem) -> list[str]:
    """Return the set of normalized identity keys for an item.

    Order matters for selecting "primary" key but for membership test all keys
    are equivalent. We prefix with namespace to avoid cross-type collisions.
    """
    keys: list[str] = []
    doi = normalize_doi(item.doi)
    if doi:
        keys.append(f"doi:{doi}")
    url = normalize_url(item.url)
    if url:
        keys.append(f"url:{url}")
    title = normalize_title(item.title)
    if title:
        keys.append(f"title:{title}")
    return keys


def load_seen(path: Path | str = DEFAULT_SEEN_PATH) -> set[str]:
    """Load the set of previously-seen keys. Returns empty set on any error."""
    p = Path(path)
    if not p.exists():
        return set()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Could not read %s: %s — starting from empty set.", p, exc)
        return set()
    keys = data.get("keys") if isinstance(data, dict) else None
    if not isinstance(keys, list):
        return set()
    return {str(k) for k in keys if k}


def save_seen(keys: Iterable[str], path: Path | str = DEFAULT_SEEN_PATH) -> None:
    """Persist the seen-key set. Sorted for stable diffs in git."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"keys": sorted(set(keys))}
    p.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def filter_unseen(
    items: list[StandardItem], seen: set[str]
) -> tuple[list[StandardItem], list[StandardItem]]:
    """Split items into (unseen, already_seen) based on the seen-key set."""
    unseen: list[StandardItem] = []
    already: list[StandardItem] = []
    for item in items:
        keys = _item_keys(item)
        if any(k in seen for k in keys):
            already.append(item)
        else:
            unseen.append(item)
    return unseen, already


def mark_seen(items: list[StandardItem], seen: set[str]) -> set[str]:
    """Return a new set including the keys from `items`."""
    updated = set(seen)
    for item in items:
        updated.update(_item_keys(item))
    return updated
