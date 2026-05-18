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

- **Only open-access sources are attempted.** Three paths, in order:
  1. arXiv abstract URLs are resolved to the `pdf` URL.
  2. URLs that already end in `.pdf` are fetched directly.
  3. For Crossref papers with a DOI, [Unpaywall](https://unpaywall.org/)
     is queried for an author-deposited open-access copy (e.g. a
     university repository). The Unpaywall API is free and requires no
     key, but a contact email is recommended via `UNPAYWALL_EMAIL`.
  Anything else (closed-access publisher pages, paywalled domains with
  no OA mirror) is skipped with status `Login Required / Skipped`.
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
| `UNPAYWALL_EMAIL` | placeholder | Email sent to Unpaywall for identification (recommended: your real address) |

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

## LLM Detailed Summarization (Optional)

For the highest-scoring open-access full-text items, the pipeline can ask
an LLM (currently Google Gemini via `google-genai`) for a structured
Korean summary covering research question, methodology, key findings,
limitations, practical value, and per-workflow relevance (PhD,
constructsteel, LCA WG). Results are attached to `metadata["llm_summary"]`
and pushed back to the matching Notion Research Items page.

**Strict scope:**

- The summarizer runs at most `LLM_MAX_ITEMS` times per pipeline
  invocation (default `1`).
- It only processes items with `score >= LLM_MIN_SCORE` (default `80`),
  `full_text_status == "Full Text Extracted"`, and a valid local
  full-text path.
- It reads at most `LLM_MAX_CHARS` characters of the extracted text
  (default `40000`).
- It is completely disabled unless `LLM_ENABLED=true` AND a provider key
  is set.
- Failures (network, parse, missing Notion property) are logged and
  swallowed — the Markdown briefing and Notion upload always continue.

### Enable locally

1. Get a Gemini API key at <https://aistudio.google.com> (sign in, click
   *Get API key* → *Create API key*). Free tier is enough for daily use
   (1500 req/day for Flash, 50 req/day for Pro).
2. Add to your `.env`:

   ```bash
   LLM_ENABLED=true
   LLM_PROVIDER=gemini
   LLM_MODEL=gemini-2.5-pro
   GEMINI_API_KEY=AIzaSy...your_key...
   LLM_MAX_ITEMS=1
   LLM_MIN_SCORE=80
   LLM_MAX_CHARS=40000
   ```

3. Run the pipeline:

   ```bash
   PYTHONPATH=src python3 -m aec_intel_agent.main
   ```

   You should see:

   ```
   INFO aec_intel_agent.llm_summarizer: LLM: summarizing N candidate(s) ...
   ```

### Enable in GitHub Actions

Add these repository secrets in **Settings → Secrets and variables →
Actions**:

| Secret name | Required? | Example value |
|---|---|---|
| `LLM_ENABLED` | yes | `true` |
| `LLM_PROVIDER` | yes | `gemini` |
| `LLM_MODEL` | yes | `gemini-2.5-pro` |
| `GEMINI_API_KEY` | yes (for Gemini) | `AIzaSy...` |
| `LLM_MAX_ITEMS` | optional | `1` |
| `LLM_MIN_SCORE` | optional | `80` |
| `LLM_MAX_CHARS` | optional | `40000` |

`OPENAI_API_KEY` and `ANTHROPIC_API_KEY` are wired up in the workflow
for future providers but are not used while `LLM_PROVIDER=gemini`.

### Today's Pick on the Daily Briefings page

Beyond per-paper summaries, the pipeline also makes a single short LLM
call each day to choose **one** paper for the user to read first. The
result is saved to the matching Daily Briefings page:

- `Today's Pick` (Rich text) — selected paper title + 3-5 sentence
  Korean reasoning explaining why it leads, framed against the user's
  PhD / constructsteel / LCA WG workflows.
- `Pick Reasoning Status` (Select: `Generated`, `Skipped`, `Failed`).

Skipped automatically when fewer than `LLM_DAILY_PICK_MIN_ITEMS` items
(default `5`) survive scoring. Disable with `LLM_DAILY_PICK_ENABLED=false`
even when the rest of the LLM step is on.

### Notion properties to add manually

The LLM summary writes to optional columns on the **Research Items**
database. The pipeline degrades gracefully if any of these is missing —
you'll just see a warning log line — but to actually see results in
Notion, add these properties to the DB:

| Property name | Type |
|---|---|
| Detailed Summary | Rich text |
| Research Question | Rich text |
| Methodology | Rich text |
| Key Findings | Rich text |
| Limitations | Rich text |
| Practical Value | Rich text |
| Relevance to PhD | Rich text |
| Relevance to constructsteel | Rich text |
| Relevance to LCA WG | Rich text |
| Read Priority | Select (options: `High`, `Medium`, `Low`) |
| LLM Summary Status | Select (options: `Summarized`, `Failed`, `Skipped - No Full Text`, `Skipped - Low Score`, `Not Attempted`) |

And on the **Daily Briefings** database:

| Property name | Type |
|---|---|
| Today's Pick | Rich text |
| Pick Reasoning Status | Select (options: `Generated`, `Skipped`, `Failed`) |

`scripts/add_llm_properties.py` adds both databases' columns in one
run; safe to re-run.

### Cost control

Gemini pricing (Google AI Studio free tier covers most daily runs):

- `gemini-2.5-pro`: 50 requests/day free; paid tier is roughly $1.25 /
  1M input tokens, $10 / 1M output.
- `gemini-2.5-flash`: 1500 requests/day free; cheaper paid tier.

With `LLM_MAX_ITEMS=1` and a typical 40k-character input, daily cost
stays at $0 in the free tier. Bump `LLM_MAX_ITEMS` only after you have
verified quality on a few real runs.

### What is summarized vs. not

| | Summarized | Not summarized |
|---|---|---|
| Score `>= LLM_MIN_SCORE` | ✅ | ❌ |
| `full_text_status == "Full Text Extracted"` | ✅ | ❌ (abstract-only, metadata-only, failed extractions) |
| Source type `paper` or `preprint` | ✅ | ❌ (blog, news, generic article) |
| Off-topic LCA (food, biofuel, …) | — | ❌ already excluded upstream by the relevance gate |

The LLM is asked to flag missing information rather than invent it, and
to keep its output strictly to the JSON schema the parser expects.

