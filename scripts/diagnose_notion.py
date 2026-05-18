"""One-shot Notion connection diagnostic.

Reads NOTION_TOKEN / NOTION_DAILY_DB_ID / NOTION_RESEARCH_DB_ID from the
environment (or .env) and reports exactly why API calls succeed or fail.
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


def _mask(value: str) -> str:
    if not value:
        return "(empty)"
    if len(value) <= 8:
        return value
    return f"{value[:4]}...{value[-4:]} (len={len(value)})"


def _check_db(token: str, label: str, db_id: str) -> None:
    print(f"\n[{label}]")
    print(f"  DB ID: {_mask(db_id)}")
    if not db_id:
        print("  ❌ DB ID is empty.")
        return

    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
    }
    url = f"https://api.notion.com/v1/databases/{db_id}"
    try:
        r = requests.get(url, headers=headers, timeout=15)
    except Exception as exc:
        print(f"  ❌ Network error: {exc}")
        return

    print(f"  HTTP {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        title = data.get("title", [])
        title_text = "".join(t.get("plain_text", "") for t in title) or "(no title)"
        print(f"  ✅ Found: {title_text!r}")
        return

    print(f"  ❌ Body: {r.text[:400]}")
    if r.status_code == 401:
        print("  → 토큰이 잘못됨 (또는 만료/재생성됨).")
    elif r.status_code == 404:
        print("  → DB ID가 잘못되었거나, 이 인테그레이션이 해당 DB에 연결되지 않음.")
        print("    Notion에서 그 DB의 ··· → Connections → AEC Intelligence Agent 추가 확인.")


def _list_accessible_databases(token: str) -> None:
    """List every database/page this integration can actually see."""
    print("\n=== Integration이 실제로 볼 수 있는 DB 목록 ===")
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    try:
        r = requests.post(
            "https://api.notion.com/v1/search",
            headers=headers,
            json={"filter": {"property": "object", "value": "database"}},
            timeout=15,
        )
    except Exception as exc:
        print(f"  ❌ Search 호출 실패: {exc}")
        return

    if r.status_code != 200:
        print(f"  ❌ HTTP {r.status_code}: {r.text[:300]}")
        return

    results = r.json().get("results", [])
    if not results:
        print("  ⚠️  접근 가능한 DB가 0개. 인테그레이션이 어디에도 연결 안 됨.")
        return

    for db in results:
        db_id = db.get("id", "(no id)")
        title_arr = db.get("title", [])
        title = "".join(t.get("plain_text", "") for t in title_arr) or "(no title)"
        print(f"  • {title!r}")
        print(f"    ID: {db_id}")


def main() -> int:
    token = os.environ.get("NOTION_TOKEN", "")
    daily = os.environ.get("NOTION_DAILY_DB_ID", "")
    research = os.environ.get("NOTION_RESEARCH_DB_ID", "")

    print("=== Notion Diagnostic ===")
    print(f"NOTION_TOKEN: {_mask(token)}")

    if not token:
        print("❌ NOTION_TOKEN 환경변수가 비어있습니다.")
        return 1

    _check_db(token, "Daily Briefings DB", daily)
    _check_db(token, "Research Items DB", research)
    _list_accessible_databases(token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
