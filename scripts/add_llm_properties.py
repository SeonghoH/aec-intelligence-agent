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


def _find_research_db_id(token: str) -> str | None:
    """Use Notion search to find a DB titled 'Research Items'."""
    r = requests.post(
        f"{API_BASE}/search",
        headers=_headers(token),
        json={"filter": {"property": "object", "value": "database"}},
        timeout=15,
    )
    r.raise_for_status()
    for db in r.json().get("results", []):
        title_parts = db.get("title", [])
        title = "".join(t.get("plain_text", "") for t in title_parts)
        if title.strip().lower() == "research items":
            return db.get("id")
    return None


# Property schema additions. Notion treats this as an idempotent merge:
# names that already exist are left alone; new names are appended.
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


def main() -> int:
    token = os.environ.get("NOTION_TOKEN", "").strip()
    if not token:
        print("❌ NOTION_TOKEN not set in environment/.env.", file=sys.stderr)
        return 1

    # Prefer .env DB ID if it works; otherwise discover via search.
    db_id = os.environ.get("NOTION_RESEARCH_DB_ID", "").strip()
    if db_id:
        r = requests.get(
            f"{API_BASE}/databases/{db_id}",
            headers=_headers(token),
            timeout=15,
        )
        if r.status_code != 200:
            print(
                f"⚠️  NOTION_RESEARCH_DB_ID returned HTTP {r.status_code}. "
                "Falling back to /search…"
            )
            db_id = None

    if not db_id:
        discovered = _find_research_db_id(token)
        if not discovered:
            print(
                "❌ Could not find a database titled 'Research Items' "
                "that this integration can access.",
                file=sys.stderr,
            )
            return 1
        print(f"ℹ️  Discovered Research Items DB id: {discovered}")
        db_id = discovered

    print(f"→ Updating Research Items DB ({db_id[:8]}…) with 11 properties.")

    r = requests.patch(
        f"{API_BASE}/databases/{db_id}",
        headers=_headers(token),
        json={"properties": PROPERTIES_TO_ADD},
        timeout=30,
    )

    if r.status_code != 200:
        print(f"❌ PATCH failed: HTTP {r.status_code}")
        print(r.text[:600])
        return 1

    print("✅ Done. Verifying current property names …")
    r = requests.get(
        f"{API_BASE}/databases/{db_id}", headers=_headers(token), timeout=15
    )
    if r.status_code == 200:
        existing = r.json().get("properties", {})
        for name in PROPERTIES_TO_ADD:
            present = "✅" if name in existing else "❌"
            print(f"  {present} {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
