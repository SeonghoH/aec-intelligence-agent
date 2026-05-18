"""One-time setup script: create the two Notion databases used by this project.

Run locally after setting NOTION_TOKEN and NOTION_PARENT_PAGE_ID in the
environment. The script prints only the new database IDs so the values can be
pasted into a local .env file.

Usage:
    NOTION_TOKEN=... NOTION_PARENT_PAGE_ID=... \\
        python3 scripts/setup_notion_databases.py
"""

from __future__ import annotations

import os
import sys
from typing import Any

import requests

NOTION_API_URL = "https://api.notion.com/v1/databases"
NOTION_VERSION = "2022-06-28"
REQUEST_TIMEOUT_SECONDS = 30


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------


def build_daily_briefings_payload(parent_page_id: str) -> dict[str, Any]:
    """Return the request body for the Daily Briefings database."""
    return {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "title": [{"type": "text", "text": {"content": "Daily Briefings"}}],
        "properties": {
            "Title": {"title": {}},
            "Date": {"date": {}},
            "Total Items": {"number": {"format": "number"}},
            "Included Items": {"number": {"format": "number"}},
            "Main Themes": {"multi_select": {"options": []}},
            "Status": {
                "select": {
                    "options": [
                        {"name": "Draft", "color": "gray"},
                        {"name": "Reviewed", "color": "blue"},
                        {"name": "Archived", "color": "default"},
                    ]
                }
            },
            "Markdown Summary": {"rich_text": {}},
            "GitHub Output Path": {"url": {}},
        },
    }


def build_research_items_payload(parent_page_id: str) -> dict[str, Any]:
    """Return the request body for the Research Items database."""
    return {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "title": [{"type": "text", "text": {"content": "Research Items"}}],
        "properties": {
            "Title": {"title": {}},
            "Published Date": {"date": {}},
            "Source": {
                "select": {
                    "options": [
                        {"name": "crossref", "color": "blue"},
                        {"name": "arxiv", "color": "orange"},
                    ]
                }
            },
            "Source Type": {
                "select": {
                    "options": [
                        {"name": "paper", "color": "green"},
                        {"name": "preprint", "color": "yellow"},
                        {"name": "article", "color": "default"},
                    ]
                }
            },
            "DOI": {"rich_text": {}},
            "URL": {"url": {}},
            "Score": {"number": {"format": "number"}},
            "Tags": {"multi_select": {"options": []}},
            "Relevance": {
                "select": {
                    "options": [
                        {"name": "High", "color": "red"},
                        {"name": "Medium", "color": "yellow"},
                        {"name": "Low", "color": "default"},
                    ]
                }
            },
            "Read Status": {
                "select": {
                    "options": [
                        {"name": "Unread", "color": "default"},
                        {"name": "Reading", "color": "blue"},
                        {"name": "Read", "color": "green"},
                        {"name": "Saved", "color": "purple"},
                    ]
                }
            },
            "Related Work": {"multi_select": {"options": []}},
            "Summary": {"rich_text": {}},
            "Why It Matters": {"rich_text": {}},
            "Relevance to Seongho": {"rich_text": {}},
            "Full-text Status": {
                "select": {
                    "options": [
                        {"name": "Not Attempted", "color": "default"},
                        {"name": "Metadata Only", "color": "gray"},
                        {"name": "Abstract Only", "color": "yellow"},
                        {"name": "Open Access PDF Found", "color": "blue"},
                        {"name": "Full Text Extracted", "color": "green"},
                        {"name": "PDF Download Failed", "color": "red"},
                        {"name": "PDF Text Extraction Failed", "color": "red"},
                        {"name": "Login Required / Skipped", "color": "orange"},
                    ]
                }
            },
            "Full-text URL": {"url": {}},
        },
    }


# ---------------------------------------------------------------------------
# Notion API
# ---------------------------------------------------------------------------


def create_database(token: str, payload: dict[str, Any]) -> str:
    """POST to the Notion API and return the created database id."""
    response = requests.post(
        NOTION_API_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data = response.json()
    db_id = data.get("id")
    if not db_id:
        raise RuntimeError("Notion API response did not include a database id.")
    return db_id


# ---------------------------------------------------------------------------
# Env handling
# ---------------------------------------------------------------------------


def _require_env(name: str) -> str:
    """Return the env var value or exit with a clear error. Never prints the value."""
    value = os.environ.get(name)
    if not value:
        sys.stderr.write(
            f"ERROR: Required environment variable {name} is not set.\n"
            f"Set it in your shell or in a local .env file before running this script.\n"
        )
        sys.exit(1)
    return value


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    token = _require_env("NOTION_TOKEN")
    parent_page_id = _require_env("NOTION_PARENT_PAGE_ID")

    daily_id = create_database(token, build_daily_briefings_payload(parent_page_id))
    research_id = create_database(token, build_research_items_payload(parent_page_id))

    print(f"NOTION_DAILY_DB_ID={daily_id}")
    print(f"NOTION_RESEARCH_DB_ID={research_id}")


if __name__ == "__main__":
    main()
