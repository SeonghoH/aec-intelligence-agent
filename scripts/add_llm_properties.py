"""Add the 11 LLM-summary properties to the Research Items database.

Idempotent: if a property already exists with the same name, Notion's
PATCH semantics leave it alone. Run multiple times safely.

Usage:
    python3 scripts/add_llm_properties.py
"""

from __future__ import annotations

import os
import sys

import requests

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

NOTION_VERSION = "2022-06-28"
API_BASE = "https://api.notion.com/v1"


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _find_db_id_by_title(token: str, wanted_title: str) -> str | None:
    """Use Notion search to find a DB by its title (case-insensitive)."""
    r = requests.post(
        f"{API_BASE}/search",
        headers=_headers(token),
        json={"filter": {"property": "object", "value": "database"}},
        timeout=15,
    )
    r.raise_for_status()
    target = wanted_title.strip().lower()
    for db in r.json().get("results", []):
        title_parts = db.get("title", [])
        title = "".join(t.get("plain_text", "") for t in title_parts)
        if title.strip().lower() == target:
            return db.get("id")
    return None


# Property schema additions for Daily Briefings DB. Hosts the "Today's
# Pick" output from the daily-pick LLM call.
DAILY_PROPERTIES_TO_ADD: dict[str, dict] = {
    "Today's Pick": {"rich_text": {}},
    "Pick Reasoning Status": {
        "select": {
            "options": [
                {"name": "Generated", "color": "green"},
                {"name": "Skipped", "color": "gray"},
                {"name": "Failed", "color": "red"},
            ]
        }
    },
}


# Property schema additions for Research Items DB. Notion treats this
# as an idempotent merge: names that already exist are left alone; new
# names are appended.
PROPERTIES_TO_ADD: dict[str, dict] = {
    "Detailed Summary": {"rich_text": {}},
    "Research Question": {"rich_text": {}},
    "Methodology": {"rich_text": {}},
    "Key Findings": {"rich_text": {}},
    "Limitations": {"rich_text": {}},
    "Practical Value": {"rich_text": {}},
    "Relevance to PhD": {"rich_text": {}},
    "Relevance to constructsteel": {"rich_text": {}},
    "Relevance to LCA WG": {"rich_text": {}},
    "Read Priority": {
        "select": {
            "options": [
                {"name": "High", "color": "red"},
                {"name": "Medium", "color": "yellow"},
                {"name": "Low", "color": "gray"},
            ]
        }
    },
    "LLM Summary Status": {
        "select": {
            "options": [
                {"name": "Summarized", "color": "green"},
                {"name": "Failed", "color": "red"},
                {"name": "Skipped - No Full Text", "color": "gray"},
                {"name": "Skipped - Low Score", "color": "gray"},
                {"name": "Not Attempted", "color": "default"},
            ]
        }
    },
}


def _resolve_db(token: str, env_var: str, fallback_title: str) -> str | None:
    """Prefer the env DB ID if it works; otherwise discover via /search."""
    db_id = os.environ.get(env_var, "").strip()
    if db_id:
        r = requests.get(
            f"{API_BASE}/databases/{db_id}",
            headers=_headers(token),
            timeout=15,
        )
        if r.status_code == 200:
            return db_id
        print(
            f"⚠️  {env_var} returned HTTP {r.status_code}. "
            f"Falling back to /search for '{fallback_title}'…"
        )
    discovered = _find_db_id_by_title(token, fallback_title)
    if discovered:
        print(f"ℹ️  Discovered {fallback_title} DB id: {discovered}")
    return discovered


def _patch_db(
    token: str, db_id: str, schema: dict[str, dict], label: str
) -> bool:
    print(
        f"→ Updating {label} DB ({db_id[:8]}…) with {len(schema)} properties."
    )
    r = requests.patch(
        f"{API_BASE}/databases/{db_id}",
        headers=_headers(token),
        json={"properties": schema},
        timeout=30,
    )
    if r.status_code != 200:
        print(f"❌ {label}: PATCH failed (HTTP {r.status_code})")
        print(r.text[:600])
        return False
    # Verify.
    r = requests.get(
        f"{API_BASE}/databases/{db_id}", headers=_headers(token), timeout=15
    )
    if r.status_code == 200:
        existing = r.json().get("properties", {})
        for name in schema:
            present = "✅" if name in existing else "❌"
            print(f"  {present} {name}")
    return True


def main() -> int:
    token = os.environ.get("NOTION_TOKEN", "").strip()
    if not token:
        print("❌ NOTION_TOKEN not set in environment/.env.", file=sys.stderr)
        return 1

    ok = True

    research_db = _resolve_db(token, "NOTION_RESEARCH_DB_ID", "Research Items")
    if research_db:
        ok = _patch_db(token, research_db, PROPERTIES_TO_ADD, "Research Items") and ok
    else:
        print("❌ Could not locate Research Items DB.", file=sys.stderr)
        ok = False

    daily_db = _resolve_db(token, "NOTION_DAILY_DB_ID", "Daily Briefings")
    if daily_db:
        ok = _patch_db(token, daily_db, DAILY_PROPERTIES_TO_ADD, "Daily Briefings") and ok
    else:
        print("❌ Could not locate Daily Briefings DB.", file=sys.stderr)
        ok = False

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
