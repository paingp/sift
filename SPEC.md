# Personal Job Board — Specification & System Design

**Version:** 1.0
**Owner:** single user (you)
**Status:** design complete, ready to build

---

## 1. Problem statement

Job aggregators are optimized for the platform, not the seeker: stale postings, duplicate
listings across boards, sponsored noise, and no memory of what you already applied to. The
goal is a private, single-user job board that ingests postings from sources you choose,
scores them against your actual resume, sorts by recency and fit, and permanently hides
anything you've already acted on.

### 1.1 Functional requirements

| ID | Requirement |
|----|-------------|
| FR-1 | Ingest job postings only from configured, interest-relevant sources and queries |
| FR-2 | Score every posting 0–100 for fit against the user's resume/profile, with explanation |
| FR-3 | Record the posting date from the original source (company career page / ATS) where available |
| FR-4 | Sort and filter by posted date (newest first) |
| FR-5 | Sort and filter by match score (best first) |
| FR-6 | Track application status per job; applied/dismissed jobs disappear from the default view |
| FR-7 | Ingestion runs unattended on a schedule with no manual babysitting |
| FR-8 | Re-ingestion never resurfaces a job the user has already actioned |

### 1.2 Non-functional requirements

- **Private by default.** Resume and application history never leave hardware you control.
- **Idempotent.** Running ingestion twice in a row changes nothing.
- **Fail-soft.** One broken source must not abort the run or corrupt the dataset.
- **Explainable.** Every score is traceable to the rubric and prompt version that produced it.
- **Boring runtime.** The nightly job is deterministic Python, not an autonomous agent.
- **Cheap.** Target $0/month marginal cost using public APIs and local inference.

### 1.3 Explicit non-goals (v1)

- Auto-submitting applications. Keep a human in the loop; it's the highest-risk automation
  and the lowest-value one.
- Multi-user, auth, hosting on the public internet.
- Beating LinkedIn on coverage. Precision beats recall for a single job seeker.
- Resume tailoring / cover-letter generation. Natural v2, but it's a separate product.

---

## 2. Prior art (what the research turned up, and what to steal)

| Project | What it does | Takeaway |
|---|---|---|
| [speedyapply/JobSpy](https://github.com/speedyapply/JobSpy) | Python lib scraping LinkedIn, Indeed, Glassdoor, Google, ZipRecruiter | Best-in-class board scraper, but LinkedIn rate-limits around page 10 and proxies are effectively required. Treat as an optional, off-by-default source. |
| [PaulMcInnis/JobFunnel](https://github.com/PaulMcInnis/JobFunnel) | Scrape → single CSV, no duplicates, status column, cron-friendly | **Archived by its maintainer**, explicitly because boards moved to aggressive anti-automation and browser-driven rescue was too fragile. This is the single most important signal in the research: HTML scraping of major boards is a maintenance treadmill. Steal its *data model* (master list + status + block lists + max listing age), not its transport. |
| [cboyd0319/JobSentinel](https://github.com/cboyd0319/JobSentinel) | Self-hosted scrape → de-dupe → score to prefs → alert, local-first | Closest analog to this project. Note its posture: explicit warnings before restricted-source actions, no credential storage, no CAPTCHA bypass, no auto-submit. Copy that posture. |
| [MadsLorentzen/ai-job-search](https://github.com/MadsLorentzen/ai-job-search) | Claude Code–native workflow: `/setup`, `/scrape`, `/apply`, `/rank` | Proves the Claude-Code-as-frontend pattern works. Its `/rank` step (batch-score then shortlist) is the right shape for the expensive scoring stage. |
| [anandanair/job-scraper](https://github.com/anandanair/job-scraper) | Scrape + resume parse + scoring + tracking on GitHub Actions | Shows the scheduled-CI deployment variant. Rejected here (see §7) because your resume would live in a repo and the runner can't reach your Ollama box. |
| Academic: [zero-shot resume↔job matching](https://www.mdpi.com/2079-9292/14/24/4960) | Structured prompts + CoT on Mistral 7B, embeddings for similarity | Validates the two-stage design: embed for retrieval/ranking, LLM with a *structured* rubric for judgment. Reported ~87% matching accuracy on specific occupations without fine-tuning. |

**Design conclusion:** the interesting projects in this space all converge on the same
pipeline — *ingest → normalize → dedupe → filter → score → track*. The differentiator is
the ingest layer. Everyone who bet on scraping big boards is fighting bot detection;
everyone who bet on ATS APIs is not. Bet on ATS APIs.

---

## 3. Data sourcing strategy

### 3.1 The core insight

"Scrape job postings" is mostly not a scraping problem. Nearly every company's careers page
is an ATS, and the major ATS platforms publish **public, unauthenticated JSON endpoints**
that companies *want* syndicated — that's how their jobs get distributed. This gives you
exactly what FR-3 asks for: the posting straight from the source of record.

### 3.2 Tier 1 — Public ATS endpoints (primary source, no auth, no key)

| ATS | Endpoint | Notes & quirks |
|---|---|---|
| Greenhouse | `https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` | One GET returns the whole board, no pagination. `content` is HTML **and HTML-escaped** — run `html.unescape()` before parsing or you get literal `&lt;p&gt;`. Dates are ISO-8601 with offset. Departments/offices are the cleanest taxonomy of any ATS. Only `updated_at` is exposed, not first-published (see §5.3). |
| Lever | `https://api.lever.co/v0/postings/{company}?mode=json` | Returns a **flat JSON array**, no wrapper object. Has `createdAt` as epoch millis — a real creation timestamp. EU-resident boards live at `api.eu.lever.co`. Officially documented for third-party use at [lever/postings-api](https://github.com/lever/postings-api). |
| Ashby | `https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true` | Best structured compensation data of the bunch — many boards publish full pay bands. Has `publishedAt`. |
| SmartRecruiters | `https://api.smartrecruiters.com/v1/companies/{company}/postings` | Only one with real limit/offset pagination — handle it. |
| Recruitee | `https://{company}.recruitee.com/api/offers/` | Simple published-jobs feed with public careers + apply URLs. |
| Workable / Personio | account-subdomain endpoints; Personio is XML (`.de` **and** `.com` variants exist) | Lower priority; add only if a target company uses one. |

**The real work here is not the HTTP call, it's the board-token directory.** There is no
cross-tenant index — you must know each company's slug. Practical approach:

1. Seed `companies.yaml` by hand with 40–80 companies you'd actually work for.
2. Discover more from Hacker News "Who is Hiring" threads via the free Algolia HN API,
   then resolve each company's careers URL to an ATS + slug.
3. Add a `resolve` CLI command: give it a careers URL, it sniffs the ATS and extracts the slug.

A curated list of 100 companies you respect will beat a keyword firehose across Indeed
every single time, and it never breaks.

### 3.3 Tier 2 — Official aggregator APIs (breadth, with free keys)

- **USAJOBS** (`https://data.usajobs.gov/api/Search`) — free API key, US federal roles.
  Given you're in Northern Virginia, this is likely a high-yield source, not a footnote.
  Supports `Keyword`, `LocationName`, `MinimumSalary`, and returns full announcement data.
- **Adzuna** (`developer.adzuna.com`) — free developer key, ~1,000 calls/month, 50+ countries,
  includes salary data. Good for broad keyword sweeps.
- **Remotive / RemoteOK / Arbeitnow** — free JSON feeds for remote roles. RemoteOK requires
  attribution; honor it.
- **HN Who's Hiring** via Algolia HN search API — keyless, and doubles as company discovery.

### 3.4 Tier 3 — Board scrapers (optional, off by default)

`python-jobspy` for LinkedIn/Indeed/Glassdoor. Include it behind a config flag with the
default `enabled: false`, plus a startup warning. Reality check from the research:

- Indeed is the most tolerant; LinkedIn rate-limits around the 10th page on a single IP.
- All board endpoints cap around 1,000 results per search.
- 429s are routine and blocking is aggressive.
- The Indeed Publisher API was retired in 2023; LinkedIn job data is behind partner-gated
  Talent Solutions. Any tutorial pointing at either is stale.

**Policy for this project:** no credential storage, no cookie replay, no CAPTCHA bypass, no
authenticated-session scraping. Respectful pacing (jittered delays, single connection) on
anything in Tier 3. If a source's ToS prohibits automated access, don't automate it — use it
manually in a browser. The Tier-1 endpoints are publisher-intended and carry none of this risk.

---

## 4. Architecture

### 4.1 Topology

Everything — development, the database, inference, the scheduled run, and the web UI — lives
on the one Ubuntu host.

```
┌──────────────────────────────────────────────────────────┐
│  Ubuntu host                                             │
│                                                          │
│  ~/jobboard/                     (git repo, working tree)│
│    ├─ .venv/                                             │
│    ├─ data/jobs.db               (SQLite, WAL)           │
│    └─ config/                                            │
│                                                          │
│  Claude Code                     (dev, in the repo)      │
│  systemd --user timer  ────────▶ jobs run --all          │
│  systemd --user service ───────▶ FastAPI 127.0.0.1:8080  │
│  Ollama                          127.0.0.1:11434         │
└──────────────────────────────────────────────────────────┘
```

Single-host has three concrete advantages here. Embedding and scoring calls to Ollama are
loopback, so nothing is exposed to the network and there's no auth layer to build. There is
no deploy step at all — the scheduled units run out of the same checkout you edit, so a
change is live on the next fire. And Claude Code can exercise the real pipeline end to end
while it writes it: hit a live ATS endpoint, write the row, score it with the actual model.

The one thing this costs you: dev and the scheduled run share a database. Use a separate
`data/dev.db` (via `JOBBOARD_DB` env var) whenever you're doing anything destructive, and
keep the nightly run pointed at `data/jobs.db`.

### 4.2 Pipeline stages

```
 [1] fetch        per-source adapters → raw JSON, persisted verbatim
        │
 [2] normalize    raw → canonical Job record (one shape for every source)
        │
 [3] dedupe       within-source by source_job_id; cross-source by canonical key
        │
 [4] filter       hard rules: location, seniority, blocklists, salary floor, staleness
        │         (kills 80–90% for free — do this BEFORE any model call)
        │
 [5] embed        Ollama /api/embed → cosine similarity vs. profile documents
        │         (cheap, ranks everything, cached by content hash)
        │
 [6] score        Ollama /api/chat with JSON-schema structured output, top-N only
        │         → subscores + evidence + gaps + final 0–100
        │
 [7] persist      job_scores rows tagged with scorer_version
        │
 [8] serve        FastAPI + HTMX web UI · CLI · MCP server for Claude Code
```

Stages 4→6 form a **funnel**: each stage is ~10× more expensive than the one before, so each
must reduce the candidate set. Never LLM-score the whole crawl.

### 4.3 Module layout

```
jobboard/
├── config/
│   ├── config.yaml          # sources, schedules, thresholds, model names
│   ├── companies.yaml       # company → {ats, slug, tags}
│   └── profile.yaml         # your constraints: location, comp floor, must-haves
├── src/jobboard/
│   ├── adapters/            # one module per source; all return list[RawPosting]
│   │   ├── base.py          # Protocol: fetch() -> list[RawPosting]
│   │   ├── greenhouse.py  lever.py  ashby.py  smartrecruiters.py
│   │   ├── recruitee.py   usajobs.py  adzuna.py  remotive.py
│   │   └── jobspy_boards.py    # Tier 3, disabled by default
│   ├── normalize.py         # RawPosting -> Job
│   ├── dedupe.py
│   ├── filters.py           # hard rules, no models
│   ├── profile.py           # resume -> structured profile + profile documents
│   ├── scoring/
│   │   ├── embed.py         # Ollama embeddings + cosine
│   │   ├── rubric.py        # prompt + JSON schema + weights; owns SCORER_VERSION
│   │   └── calibrate.py     # scores a labeled set, reports correlation
│   ├── store/               # SQLAlchemy models, migrations, repository funcs
│   ├── service.py           # the ONLY business-logic entrypoint (see §4.4)
│   ├── cli.py               # Typer
│   ├── web/                 # FastAPI + Jinja/HTMX
│   └── mcp_server.py        # exposes service.py to Claude Code
├── tests/fixtures/          # recorded API responses per adapter
└── deploy/                  # systemd units, install script
```

### 4.4 The one architectural rule that matters

**All three frontends (CLI, web, MCP) call the same `service.py`.** No business logic in a
route handler, no SQL in the CLI. This is what lets you add the MCP server in an afternoon
and keeps Claude Code from writing three divergent implementations of "mark applied."

---

## 5. Data model

### 5.1 Schema (SQLite)

```sql
CREATE TABLE companies (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  canonical_name TEXT NOT NULL UNIQUE,   -- lowercased, suffixes stripped
  ats TEXT,                              -- greenhouse | lever | ashby | ...
  ats_slug TEXT,
  careers_url TEXT,
  tags TEXT,                             -- JSON array: sector, size, "dream", ...
  blocked INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE jobs (
  id INTEGER PRIMARY KEY,
  company_id INTEGER NOT NULL REFERENCES companies(id),
  source TEXT NOT NULL,                  -- adapter name
  source_job_id TEXT NOT NULL,
  canonical_key TEXT NOT NULL,           -- see §5.2
  title TEXT NOT NULL,
  location_raw TEXT,
  location_normalized TEXT,
  remote_type TEXT,                      -- onsite | hybrid | remote | unknown
  employment_type TEXT,
  description_md TEXT,
  apply_url TEXT NOT NULL,               -- canonical company/ATS URL, never a redirect
  salary_min INTEGER, salary_max INTEGER, salary_currency TEXT,
  source_posted_at TIMESTAMP,            -- from the source, may be NULL
  date_precision TEXT NOT NULL,          -- exact | updated_only | inferred  (§5.3)
  first_seen_at TIMESTAMP NOT NULL,
  last_seen_at  TIMESTAMP NOT NULL,
  content_hash TEXT NOT NULL,            -- change detection
  closed_at TIMESTAMP,                   -- set when it stops appearing in the feed
  raw_json TEXT NOT NULL,
  UNIQUE (source, source_job_id)
);
CREATE INDEX idx_jobs_canonical ON jobs(canonical_key);
CREATE INDEX idx_jobs_sort ON jobs(COALESCE(source_posted_at, first_seen_at) DESC);

CREATE TABLE job_scores (
  id INTEGER PRIMARY KEY,
  job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  scorer_version TEXT NOT NULL,          -- "v3:qwen2.5:14b:rubric-2026-08"
  embedding_similarity REAL,
  score_total INTEGER NOT NULL,          -- 0-100
  subscores TEXT NOT NULL,               -- JSON: must_have, nice_to_have, seniority, domain, logistics
  evidence TEXT,                         -- JSON: resume lines supporting the score
  gaps TEXT,                             -- JSON: requirements you don't meet
  verdict TEXT,                          -- strong | good | stretch | poor
  scored_at TIMESTAMP NOT NULL,
  UNIQUE (job_id, scorer_version)
);

CREATE TABLE applications (
  id INTEGER PRIMARY KEY,
  canonical_key TEXT NOT NULL UNIQUE,    -- keyed to the ROLE, not the posting row (§5.4)
  job_id INTEGER REFERENCES jobs(id),    -- the posting that triggered it
  status TEXT NOT NULL,                  -- interested|applied|screening|interview|offer|rejected|withdrawn|dismissed
  applied_at TIMESTAMP,
  notes TEXT,
  updated_at TIMESTAMP NOT NULL
);

CREATE TABLE runs (
  id INTEGER PRIMARY KEY,
  started_at TIMESTAMP, finished_at TIMESTAMP,
  source TEXT, status TEXT,              -- ok | partial | failed
  fetched INTEGER, new INTEGER, updated INTEGER, closed INTEGER,
  error TEXT
);

CREATE TABLE embeddings (
  content_hash TEXT PRIMARY KEY,
  model TEXT NOT NULL,
  vector BLOB NOT NULL                   -- float32 packed
);
```

### 5.2 Canonical key (dedupe + application persistence)

```
canonical_key = sha1(
    normalize_company(company_name) + "|" +
    normalize_title(title)          + "|" +
    normalize_location(location)
)
```

- `normalize_company`: lowercase, strip `inc|llc|ltd|corp|gmbh|,|.`
- `normalize_title`: lowercase, strip req IDs `(R-12345)`, seniority-neutral punctuation,
  collapse whitespace. Keep the seniority *word* — "Senior Engineer" ≠ "Engineer".
- `normalize_location`: map to metro (`Reston, VA` / `Washington, DC-Baltimore` / `Remote (US)`).

This key is the backbone of FR-8. It survives repostings, ATS migrations, and the same role
appearing on Greenhouse and Adzuna simultaneously.

### 5.3 The posting-date problem (FR-3) — read this carefully

This is the requirement most likely to quietly produce wrong output, because **ATS APIs do
not agree on what "posted" means**:

| Source | Field available | What it actually is |
|---|---|---|
| Lever | `createdAt` (epoch ms) | true creation time → `date_precision = exact` |
| Ashby | `publishedAt` | true publish time → `exact` |
| Greenhouse | `updated_at` only | last edit, which bumps on any description tweak → `updated_only` |
| USAJOBS | `PublicationStartDate` | exact |
| Adzuna | `created` | exact-ish (aggregator's ingest time) |
| Board scrapers | "3 days ago" strings | must be parsed relative to fetch time → `inferred` |

Design rules:

1. Store `source_posted_at` **and** `date_precision` **and** `first_seen_at`. Never collapse them.
2. Sort key: `COALESCE(source_posted_at, first_seen_at) DESC`.
3. For `updated_only` sources, once you've seen a job, **freeze** your recorded date to the
   earliest value you ever observed. Otherwise a typo fix on a 3-month-old Greenhouse posting
   catapults it to the top of your board — the single most common bug in DIY job aggregators.
4. Surface precision in the UI: an exact date renders plain, an inferred one renders with a
   `~` and a tooltip. You'll make better decisions when you know which dates you can trust.

### 5.4 Applied-tracking semantics (FR-6, FR-8)

Application rows key on `canonical_key`, **not** `job_id`. Consequences, all desirable:

- Company deletes and reposts the req with a new ATS ID → same canonical key → stays hidden.
- The same role arrives later via Adzuna → same canonical key → stays hidden.
- Rows are never deleted. `dismissed` is a first-class status; "not interested" is data.
- Default board query: `WHERE canonical_key NOT IN (SELECT canonical_key FROM applications
  WHERE status IN ('applied','screening','interview','offer','rejected','withdrawn','dismissed'))`.
- `interested` stays *visible* — it's a shortlist, not a removal.
- The UI needs a "show hidden" toggle and an undo, or you'll dismiss something by accident
  and lose it forever.

---

## 6. Matching & scoring design

### 6.1 Building the profile

Parse your resume once into a structured profile (`profile.yaml` + generated JSON):

- **Skills** with evidence and recency: `{skill, years, last_used, evidence: "line from resume"}`
- **Seniority band** and total relevant years
- **Domains** (fintech, gov/defense, infra, ML, ...)
- **Hard constraints**: geography/commute radius, remote requirement, comp floor,
  work authorization, clearance status, industries to avoid
- **Profile documents** for embedding: don't embed the whole resume as one blob. Generate
  3–5 focused paragraphs ("what I do," "core stack," "domains," "ideal role") — they embed
  far better than a bullet-list resume and let you see *which facet* matched.

Have Claude Code generate the first draft of `profile.yaml` from your resume, then hand-edit.
The hand-editing is where the accuracy comes from.

### 6.2 Stage 4 — hard filters (free, deterministic)

Runs before any model. Rejects with a logged reason:

```yaml
filters:
  max_age_days: 30
  locations: ["Reston, VA", "Washington, DC metro", "Remote (US)"]
  exclude_titles: ["intern", "unpaid", "commission only", "clearance required: TS/SCI"]
  exclude_companies: ["<staffing agencies you don't want>"]
  seniority_band: [mid, senior, staff]
  salary_floor: 150000        # applied only when salary data exists
  require_us_work_auth_ok: true
```

Log every rejection with its reason. When your board looks empty, the rejection log tells you
which filter is too aggressive — without it you'll be debugging blind.

### 6.3 Stage 5 — embedding similarity (cheap, ranks everything)

- Ollama `POST /api/embed`, model `nomic-embed-text` (large context, strong on long text) or
  `embeddinggemma` / `bge-m3` if you want to compare. Pick one and pin it — changing the
  embedding model invalidates every cached vector.
- Cosine similarity between each profile document and the job description; take max and mean.
- Cache by `content_hash` in the `embeddings` table. Re-embed only on content change.
- At your scale (thousands of jobs, not millions), **do not add a vector database.** NumPy
  brute-force over a few thousand float32 vectors is sub-millisecond. `sqlite-vec` is a fine
  option but is still pre-1.0 alpha with breaking changes expected — not worth the dependency
  here.
- Use this to select the top N (say 40) candidates per run for expensive scoring.

### 6.4 Stage 6 — LLM rubric scoring (expensive, top-N only)

Use Ollama's **structured outputs**: pass a JSON schema (or a Pydantic
`model_json_schema()`) to the `format` parameter of `/api/chat`. This constrains generation
to your schema, so you get parseable output instead of regexing prose. Note that Ollama's
*cloud* offering doesn't support structured outputs — you're running locally, so you're fine.

```python
class Subscores(BaseModel):
    must_have_coverage: int   # 0-40  — the requirements marked required
    nice_to_have: int         # 0-15
    seniority_fit: int        # 0-20  — under/over-qualified both penalized
    domain_fit: int           # 0-15
    logistics: int            # 0-10  — location, remote, comp, auth

class JobScore(BaseModel):
    subscores: Subscores
    matched_requirements: list[str]
    unmet_requirements: list[str]
    evidence: list[str]        # quoted lines from the profile, not invented
    verdict: Literal["strong", "good", "stretch", "poor"]
    reasoning: str             # <= 3 sentences
```

**`score_total` is computed in Python as the sum of subscores — never asked for from the
model.** Left to itself, an LLB asked for "a match score out of 100" returns 72–85 for
almost everything; the distribution collapses and sorting becomes meaningless. Forcing
bounded subscores that you sum yourself restores spread and makes the number auditable.

Other rules that keep this honest:

- `temperature: 0`, fixed seed where supported.
- Pass the *structured profile*, not the raw resume — less noise, shorter prompt, better recall.
- Require `evidence` to be verbatim substrings of the profile; validate this in Python and
  penalize/flag when it fails. This is your cheapest hallucination detector.
- Ask the model to extract the job's requirements *first*, then evaluate each — chain-of-thought
  through structure, not through prose.
- Stamp every row with `scorer_version = "{schema_rev}:{model}:{prompt_rev}"`. When any part
  changes, old scores become non-comparable and must be recomputed. Sorting a list where half
  the scores came from a different rubric is silently wrong.

### 6.5 Calibration (do not skip)

Build `calibrate.py` and a `tests/labeled_jobs.jsonl` of ~25 postings you rate by hand
0–100. On any rubric or model change, run it and report Spearman correlation plus mean
absolute error. Target ρ > 0.7. Without this you have no idea whether a prompt "improvement"
made things worse, and you will change the prompt a lot.

**Model choice on your Ollama box:** a 7–14B instruct model (Qwen 2.5 14B, Llama 3.1 8B,
Mistral) is sufficient — this is structured extraction and comparison, not reasoning-heavy
work. 40 jobs × ~4k tokens is a few minutes on modest hardware, comfortably inside a nightly
window. Configure `OLLAMA_KEEP_ALIVE` so the model isn't reloaded per request.

---

## 7. Scheduling & deployment

### 7.1 What runs the schedule

The scheduler needs to reach the SQLite file and the Ollama instance, both of which are
local. That rules out everything hosted elsewhere:

| Option | Verdict for this project |
|---|---|
| Claude Code `/loop` (CLI) | **No.** Session-scoped — dies when the session exits, requires an open session, and recurring tasks auto-expire after 7 days. Built for polling a build, not durable automation. |
| Claude Code Desktop scheduled tasks | **No.** macOS/Windows only; this host is Linux. |
| Claude Code Routines (cloud) | **No.** Runs on Anthropic's infrastructure against a fresh clone with no local file access — it can't reach Ollama on loopback or the SQLite file. Minimum interval is 1 hour. Excellent for repo automation, wrong tool here. |
| GitHub Actions on a `schedule` trigger | **No.** Same reachability problem, plus your resume and application history would have to live in a repo. |
| **systemd timer** | **Yes.** Local to the data and to Ollama, zero external dependencies, free, private. |

Use a **systemd timer, not cron**, for four concrete reasons: `Persistent=true` runs a missed
job after a reboot (cron silently skips it); output goes to journald with no shell redirection
gymnastics; `RandomizedDelaySec` spreads load; and `systemctl status` tells you what happened
last night in one command.

Use **user units**, not system units. They run as you, out of your own checkout, with your
own venv and env vars — no permission juggling between the code you're editing and the code
that's running, and no `sudo` in the edit-test loop. The only setup cost is enabling lingering
once so your units run when you're not logged in.

```ini
# ~/.config/systemd/user/jobboard-ingest.service
[Unit]
Description=Job board ingest and scoring
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=%h/jobboard
ExecStart=%h/jobboard/.venv/bin/jobs run --all
TimeoutStartSec=3600
Environment="OLLAMA_HOST=http://127.0.0.1:11434"
Environment="JOBBOARD_DB=%h/jobboard/data/jobs.db"
```

```ini
# ~/.config/systemd/user/jobboard-ingest.timer
[Unit]
Description=Run job board ingest on a schedule

[Timer]
OnCalendar=*-*-* 03:17:00      # odd minute, not :00 — avoids thundering-herd hours
RandomizedDelaySec=900
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo loginctl enable-linger $USER          # once: user units run without an active login
systemctl --user daemon-reload
systemctl --user enable --now jobboard-ingest.timer
systemctl --user list-timers jobboard-ingest.timer   # confirm next fire
journalctl --user -u jobboard-ingest -n 100          # read last night's run
```

Because the units point at your working tree, there is no deploy step: edit, commit, and the
next fire picks it up. The corollary is that a broken commit breaks tonight's run — so make
`uv run pytest` a habit before you walk away, and let the digest (§7.4) tell you if a run
failed.

### 7.2 On "every other night" — a recommendation

You asked for every other night. **I'd suggest nightly instead**, for these reasons:

- The marginal cost is near zero. Tier-1 ATS calls are a few hundred cheap GETs. Scoring is
  bounded by your top-N cap, not by crawl size, so a nightly run costs roughly the same
  compute as a bi-nightly one — it just splits it into smaller batches.
- Freshness is the whole point. Competitive roles accumulate hundreds of applicants within
  48 hours. A 48-hour cadence means your *average* posting is ~24h stale before you see it,
  and worst case 48h. Nightly halves that.
- Incremental runs fail smaller. If a source breaks, you lose one night, not two.

If you still want every other night, it's a one-line change: `OnCalendar=*-*-1/2 03:17:00`.
The pipeline is idempotent either way. A genuine middle ground: ingest nightly (cheap,
keeps dates accurate) and run LLM scoring only on new/changed jobs — which is the design
already, so nightly is essentially free.

Bi-weekly is where I'd draw the line: at that cadence `date_precision` degrades badly for
sources without exact dates, because `first_seen_at` becomes a poor proxy for posted date.

### 7.3 Viewing the board

FastAPI binds to `127.0.0.1:8080`. If you work on this host directly, open a browser there
and you're done — no auth, no exposure, nothing further to configure.

If the host is headless and you want the UI in a browser elsewhere, the options in order of
preference:

1. **Tailscale** — `tailscale serve --bg 8080` puts the UI on your tailnet with HTTPS. No
   port forwarding, no public exposure, no auth layer to write, works from a phone.
2. **SSH tunnel** — `ssh -L 8080:127.0.0.1:8080 <host>`. Zero setup, but you re-establish it
   every session.
3. **Reverse proxy on a public port** — don't. You'd have to build auth, and this database
   holds your resume and application history.

Either way, keep the bind address at `127.0.0.1`. Never `0.0.0.0`.

### 7.4 Operational hygiene

- **Digest on completion:** the run writes a short summary (new jobs, top 5 by score, source
  failures) to a file, and optionally pushes it via ntfy/Telegram/email. This is what makes it
  "no monitoring needed" — you get pinged when there's something to look at, and pinged
  differently when a source has been failing for 3 consecutive runs.
- **Schema-drift alarm:** if an adapter returns 0 jobs for a company that returned >0 last
  run, that's a drift signal, not an empty board. Alert on it. ATS endpoints are stable but
  not immutable.
- **Backups:** `sqlite3 jobs.db ".backup"` nightly to a second path, keep 7. Your application
  history is irreplaceable; the job postings are not.
- **Retention:** mark jobs `closed_at` when they vanish from a feed rather than deleting.
  Historical postings are useful and storage is free.

---

## 8. UI requirements

Minimum viable board (FastAPI + Jinja + HTMX — no build step, no npm, Claude Code writes it fast):

- **Default view:** unactioned jobs, sorted by score desc, secondary sort date desc.
- **Sort toggle:** `date` ⇄ `score`. Also offer a blended sort:
  `score * exp(-age_days / 14)` — surfaces strong-and-fresh over strong-and-stale.
- **Row:** title · company · location · posted date (with precision indicator) · score badge ·
  verdict · salary if known.
- **Expand:** subscore breakdown, matched requirements, gaps, evidence, description, apply link.
- **Actions (one click, HTMX, no page reload):** Applied · Dismiss · Interested · Undo.
- **Filters:** company tag, source, remote type, min score, max age, "show hidden".
- **Health strip:** last run time, per-source status, count of new jobs.

Do not build a SPA. This is a single-user list view; the framework overhead exceeds the value.

---

## 9. Risks & mitigations

| Risk | Mitigation |
|---|---|
| ATS endpoint changes shape | Fixture-based contract tests per adapter + drift alarm on zero-result boards |
| Score inflation makes sorting useless | Computed subscore sum, not model-reported total; calibration set with correlation target |
| LLM invents resume evidence | Validate `evidence` strings against the profile text in Python |
| Board scraper gets you rate-limited or blocked | Tier 3 off by default; jittered pacing; never store credentials or replay cookies |
| Greenhouse `updated_at` churn reorders the board | Freeze earliest observed date per canonical key |
| Applied job resurfaces after repost | Applications keyed on canonical_key, not job_id |
| Resume PII leaks to a repo or third party | `data/` and `profile.yaml` gitignored; local Ollama only; no cloud LLM in the nightly path |
| Silent failure for weeks | Run digest + escalating alert after N consecutive source failures |
| Filters too tight, board looks empty | Log every rejection with reason; `jobs why <id>` explains any exclusion |

---

## 10. Milestones

| Phase | Deliverable | Rough effort |
|---|---|---|
| 0 | Repo, config schema, DB migrations, CI | half a session |
| 1 | Greenhouse adapter → DB, end to end | one session |
| 2 | Normalize, dedupe, 5 more adapters | one session |
| 3 | Profile extraction + hard filters | one session |
| 4 | Embedding stage + caching | half a session |
| 5 | LLM rubric scoring + calibration harness | one to two sessions |
| 6 | Application tracking + state machine | half a session |
| 7 | Web UI | one session |
| 8 | CLI polish + MCP server | half a session |
| 9 | Schedule it: systemd user units, digest, backups | one session |

Build guide with per-phase Claude Code prompts: see `BUILD_GUIDE.md`.
