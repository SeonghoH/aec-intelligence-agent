# AEC Intelligence Agent

Initial MVP skeleton for a Python-based AEC intelligence agent.

The future agent will collect daily papers and news about BIM, openBIM, digital architecture, construction technology, digital twins, AI in construction, structural steel, steel construction, and LCA / embodied carbon.

This MVP only includes:

- A `StandardItem` Pydantic model
- Placeholder collectors
- Config-driven keyword scoring
- DOI and URL deduplication
- Markdown briefing generation
- Basic tests

It does not include a dashboard, Notion integration, email, vector database, frontend UI, or multi-agent logic.

## Requirements

- Python 3.11+

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Run The MVP

```bash
aec-intel-agent
```

Or, without installing the console script:

```bash
PYTHONPATH=src python -m aec_intel_agent.main
```

The command writes a Markdown briefing to `outputs/`.

## Run Tests

```bash
pytest
```

## Notion Database Setup (Optional)

The MVP does not push results to Notion yet, but you can pre-create the two
databases the future integration will use. The setup is a one-time local step.

### 1. Create a Notion integration

1. Go to <https://www.notion.so/my-integrations>.
2. Click **New integration**, give it a name (e.g. `aec-intelligence-agent`),
   choose the workspace, and submit.
3. On the integration page, copy the **Internal Integration Token**. Keep it
   secret — do not commit it to git.

### 2. Connect the integration to a parent page

1. In Notion, open (or create) the page that will hold the two databases.
2. Click the **⋯** menu (top-right) → **Connections** → **Add connections**.
3. Pick the integration you just created. It now has access to that page and
   its children.

### 3. Find the parent page ID

1. Open the parent page in your browser.
2. The URL looks like
   `https://www.notion.so/Workspace/My-Page-2f1ab3cdef4567890abcdef1234567890`.
3. The final 32 hex characters (with or without dashes) are the page ID.

### 4. Run the setup script

```bash
NOTION_TOKEN=secret_xxx \
NOTION_PARENT_PAGE_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx \
python3 scripts/setup_notion_databases.py
```

The script only prints the two created database IDs:

```
NOTION_DAILY_DB_ID=...
NOTION_RESEARCH_DB_ID=...
```

### 5. Save the IDs

Copy both values into your local `.env` file (see `.env.example`):

```
NOTION_DAILY_DB_ID=...
NOTION_RESEARCH_DB_ID=...
```

Do not commit `.env`.

## Notion Upload (Optional, Automatic)

When all three environment variables are present at runtime, the pipeline
uploads results to Notion automatically right after writing the Markdown
briefing. If any variable is missing or empty, the upload is skipped
silently and only the Markdown file is produced.

**Required environment variables**

| Variable | Purpose |
|---|---|
| `NOTION_TOKEN` | Internal Integration Token from your Notion integration |
| `NOTION_DAILY_DB_ID` | Database ID printed by `scripts/setup_notion_databases.py` |
| `NOTION_RESEARCH_DB_ID` | Database ID printed by `scripts/setup_notion_databases.py` |

**What gets uploaded**

- One page per day in **Daily Briefings** (title, date, item counts, main
  themes, status, the full Markdown, GitHub output path).
- One page per included research item in **Research Items** (title,
  published date, source, type, DOI, URL, score, tags, relevance, read
  status, summary, why it matters, relevance to Seongho, full-text status).

**Duplicate handling**

- **Daily Briefings:** deduplicated by `Date`. If a page with the same date
  already exists, the upload is skipped and the log shows
  `Notion: daily briefing already exists for YYYY-MM-DD, skipped.` To force
  a refresh, delete the existing page in Notion first.
- **Research Items:** deduplicated by `DOI` → `URL` → `Title` (in priority
  order). The first non-empty key is used:
  1. **DOI** — lowercased and stripped of any `https://doi.org/` prefix
     before matching (case-insensitive).
  2. **URL** — trailing slashes, UTM parameters, and host casing are
     normalized before matching.
  3. **Title** — used only when both DOI and URL are missing. The match is
     case-sensitive and whitespace-sensitive on the Notion side (Notion's
     API can't normalize titles in filters). This is a documented MVP
     limitation; in practice, items that reach the title fallback are rare.
- Failed duplicate checks do not crash the pipeline. The item is counted
  in `items_failed`, a warning is logged, and the run continues. The final
  log line is:
  `Notion upload complete: daily_created=N, daily_skipped=N, items_uploaded=N, items_skipped=N, items_failed=N.`

**Local testing**

1. Put the three variables in a `.env` file (already in `.gitignore`).
2. Export them in your shell:
   ```bash
   set -a; source .env; set +a
   ```
3. Run the pipeline:
   ```bash
   python3 -m aec_intel_agent.main
   ```
4. Check the two databases in Notion for new entries.

If something fails (bad token, integration not connected to the parent
page, Notion rate limit, etc.), the error is logged and the Markdown
briefing is still produced.

## Open-Access Full-text Discovery (Optional)

After scoring, the pipeline attempts to find and extract open-access full
text for a small number of the highest-relevance research items. This is
strictly conservative:

- **Only open-access sources are attempted.** arXiv abstract URLs are
  resolved to their `pdf` URL; URLs that already end in `.pdf` are
  fetched directly. Anything else (publisher landing pages, paywalled
  domains) is skipped with status `Login Required / Skipped`.
- **No login, no cookies, no scraping.** Browser automation, paywall
  bypass, and login flows are explicitly not implemented.
- **PDFs are never persisted.** They are downloaded into memory with a
  size cap (20 MB) and a request timeout. After text extraction the
  bytes are discarded.
- **Extracted text is local-debug-only.** If text is recovered it is
  written to `data/full_text/{slug}.txt`. That directory is gitignored
  and never uploaded to Notion or as a workflow artifact.
- **No LLM summarization.** This step only extracts raw text — what
  happens next is a separate, future concern.

**Candidate selection rules**

1. `score >= 80`
2. `source_type` is `paper` or `preprint`
3. At most `FULL_TEXT_MAX_ITEMS` items per run (default `3`)

**Environment variables**

| Variable | Default | Purpose |
|---|---|---|
| `FULL_TEXT_MAX_ITEMS` | `3` | Cap on the number of items processed per run |
| `FULL_TEXT_MAX_CHARS` | `60000` | Cap on the size of extracted text per item |

**Status values (written to Notion's `Full-text Status` select field)**

- `Not Attempted` — default for items below threshold
- `Open Access PDF Found` — PDF URL detected
- `Full Text Extracted` — PDF downloaded and text recovered
- `PDF Download Failed` — network error, timeout, paywall HTML response,
  or size cap exceeded
- `PDF Text Extraction Failed` — PDF could not be parsed
- `Login Required / Skipped` — URL was not a recognized open-access form
- `Metadata Only` / `Abstract Only` — reserved for future use

**What Notion stores**

- `Full-text Status` (always written)
- `Full-text URL` (only when an open-access PDF URL was detected, and
  only if your Research Items DB schema includes this property — the
  upload falls back gracefully if it does not)
- The full extracted text is **not** uploaded to Notion.

If you ran `scripts/setup_notion_databases.py` before this release, the
new status options and the `Full-text URL` property won't exist in your
Research Items DB yet. Either re-run the setup script (which creates a
fresh DB) or add the property and options manually.

## GitHub Actions Secrets

To enable Notion upload from the daily workflow, add three repository
secrets at **Settings → Secrets and variables → Actions → New repository
secret**:

| Secret name | Value |
|---|---|
| `NOTION_TOKEN` | the Internal Integration Token |
| `NOTION_DAILY_DB_ID` | the Daily Briefings database ID |
| `NOTION_RESEARCH_DB_ID` | the Research Items database ID |

The workflow passes these as environment variables to the briefing step
only. Their values are never printed. If you skip adding these secrets,
the workflow continues to work and only produces the Markdown briefing.

