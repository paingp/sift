# Building the Job Board with Claude Code — Step by Step

Companion to `SPEC.md`. Each phase is a self-contained working session ending in something
that runs. Copy the prompts, adjust the specifics, review the plan before approving.

---

Everything below runs on the Ubuntu host — you develop, test, schedule, and browse in the
same place. There is no deploy step.

---

## Before Phase 0 — one-time host setup

```bash
# Claude Code
curl -fsSL https://claude.ai/install.sh | bash    # or: npm i -g @anthropic-ai/claude-code
claude                                            # authenticate once

# uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# confirm Ollama is up and pull the two models the pipeline needs
curl -s http://127.0.0.1:11434/api/tags | head
ollama pull nomic-embed-text
ollama pull qwen2.5:14b        # or whatever instruct model you're running

mkdir -p ~/jobboard && cd ~/jobboard && git init
```

Two settings worth doing now rather than debugging later:

```bash
sudo loginctl enable-linger $USER      # user systemd units run without an active login
```

and in `/etc/systemd/system/ollama.service.d/override.conf` (or however your Ollama is
configured), set `OLLAMA_KEEP_ALIVE=30m` so the model isn't unloaded and reloaded between
scoring calls. Without it, a 40-job scoring batch pays the model load cost repeatedly.

If you're SSH'd in, run Claude Code inside `tmux` or `screen`. A dropped connection
mid-session is otherwise a lost session.

---

## 0. Ground rules that make Claude Code work well here

**Build vertical slices, not layers.** "Greenhouse jobs land in SQLite and I can `SELECT`
them" is a good phase. "All the adapters" or "the whole data layer" is not — you won't find
out something is wrong until much later, when it's expensive to fix.

**Use plan mode for anything structural.** Press `Shift+Tab` twice to enter plan mode.
Claude proposes, you correct, then it executes. The corrections are cheap at plan time and
expensive after 600 lines of code exist.

**Commit at every phase boundary.** Ask for a commit as the last step of each session. Easy
rollback matters more than usual here because you'll be changing the scoring rubric a lot.

**Give it the spec.** Put `SPEC.md` in the repo root and reference it explicitly:
"Follow the schema in SPEC.md §5.1 exactly." It's much better at implementing a written
decision than at inferring one.

**Insist on fixtures over live calls in tests.** Every adapter test must run offline against
a recorded JSON response. Otherwise your test suite depends on someone else's uptime and
fails at 3am for no reason.

**Do not let it install a vector database, Docker Compose, Celery, Redis, or a React
frontend.** It will offer. For a single-user board over a few thousand rows, every one of
those is a net negative. Say so in `CLAUDE.md` and it'll stop offering.

**Protect the real database.** Developing on the host means Claude Code can reach
`data/jobs.db` — the one holding your application history. Export
`JOBBOARD_DB=$PWD/data/dev.db` in your shell before any session that touches migrations or
the store layer, and tell Claude Code that `data/jobs.db` is off limits. The nightly unit
sets its own `JOBBOARD_DB` explicitly, so the two never collide.

**Take advantage of the live services.** Claude Code is running on the same host as Ollama,
the database, and an open internet connection, so it can curl a real ATS endpoint, make a
real inference call, and inspect the actual DB. Use that: "hit the live
Greenhouse endpoint for slug X, save the response to tests/fixtures/, then write the parser
against it" is a better instruction than describing the shape from the spec.

---

## Phase 0 — Scaffold

```
Read SPEC.md. Set up the project skeleton only — no business logic yet.

- Python 3.12, uv for dependency management, src layout, package name `jobboard`.
- Dependencies: httpx, pydantic v2, pydantic-settings, sqlalchemy, alembic, typer,
  pyyaml, tenacity, structlog, numpy. Dev: pytest, pytest-httpx, ruff, mypy.
- Create the module layout from SPEC.md §4.3 with empty stubs and docstrings.
- Implement config loading: config/config.yaml, config/companies.yaml,
  config/profile.yaml -> typed pydantic-settings models. Fail loudly with a clear
  message on a malformed config.
- Alembic migration creating every table in SPEC.md §5.1, verbatim.
- `jobs` CLI entrypoint (typer) with subcommands stubbed: ingest, score, run, list,
  apply, dismiss, why, serve, doctor.
- `jobs doctor` should actually work: check DB reachable, migrations current,
  Ollama reachable at OLLAMA_HOST, config valid. Print a table.
- .gitignore must exclude: data/, *.db, config/profile.yaml, config/companies.yaml,
  .env, resume.*
- pytest configured, one smoke test, ruff + mypy clean.

Do not implement any adapter or scoring logic in this phase.
```

**Done when:** `uv run jobs doctor` prints a green table and `alembic upgrade head` creates
the schema.

---

## Phase 1 — First adapter, end to end

The most important phase. Everything after this is repetition.

```
Implement the Greenhouse adapter and the ingest path end to end for a single company.

- adapters/base.py: a `SourceAdapter` Protocol with `name: str` and
  `fetch(config) -> list[RawPosting]`. RawPosting is a pydantic model holding
  source, source_job_id, raw dict, and fetched_at.
- adapters/greenhouse.py: GET https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true
  - one request returns the whole board, no pagination
  - the `content` field is HTML AND html-escaped: html.unescape() before parsing
  - convert description HTML to markdown
  - httpx with a descriptive User-Agent, 30s timeout, tenacity retry with exponential
    backoff on 5xx and timeouts only (never retry 4xx)
- normalize.py: RawPosting -> Job per SPEC.md §5.1. Greenhouse exposes only
  `updated_at`, so set date_precision='updated_only' and source_posted_at=updated_at.
- store: upsert on (source, source_job_id). On conflict update last_seen_at and
  content_hash; if source_posted_at moves LATER on an 'updated_only' record, keep the
  EARLIER stored value (SPEC.md §5.3 rule 3). Write a runs row.
- `jobs ingest --source greenhouse --company <slug>` runs it.

Tests: record one real Greenhouse response into tests/fixtures/greenhouse_board.json
(hit the live API once yourself to capture it, then never again). Test with pytest-httpx:
parsing, unescaping, upsert idempotency, and the date-freeze rule specifically.
```

**Done when:** running ingest twice produces the same row count and identical
`source_posted_at` values, and the date-freeze test passes. Verify by hand:

```bash
uv run jobs ingest --source greenhouse --company anthropic
sqlite3 data/jobs.db "select title, source_posted_at, date_precision from jobs limit 10"
```

---

## Phase 2 — The rest of the sources + dedupe

```
Add the remaining Tier 1 and Tier 2 adapters following the Greenhouse pattern exactly.
Each gets its own fixture file and its own tests. Per SPEC.md §3.2/§3.3:

- lever: api.lever.co/v0/postings/{slug}?mode=json — returns a FLAT ARRAY, not a
  wrapper object. createdAt is epoch milliseconds -> date_precision='exact'.
- ashby: api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true —
  parse the compensation object into salary_min/max/currency. publishedAt -> 'exact'.
- smartrecruiters: api.smartrecruiters.com/v1/companies/{slug}/postings — this one
  paginates with limit/offset. Handle it.
- recruitee: https://{slug}.recruitee.com/api/offers/
- usajobs: data.usajobs.gov/api/Search — needs an API key header plus a User-Agent
  set to the registered email. Key from env, never committed. Map PublicationStartDate.
- adzuna: developer.adzuna.com — app_id + app_key from env. Rate limit: stay well
  under 1000 calls/month, so cap queries per run and log usage.

Then implement dedupe.py per SPEC.md §5.2: canonical_key from normalized
company + title + location. Write extensive unit tests for the normalizers —
"Sr. Software Engineer (R-4471)" and "Senior Software Engineer" must collide;
"Senior Software Engineer" and "Staff Software Engineer" must not.

Add a `resolve` command: given a careers page URL, sniff which ATS it is and extract
the slug, then append to companies.yaml.

Every adapter must fail independently: if Lever 500s, the run continues and records
status='partial' with the error on the runs row. Never let one source abort the batch.
```

**Done when:** `jobs ingest --all` pulls from every configured source, one deliberately
broken source doesn't stop the run, and the dedupe test suite is green.

---

## Phase 3 — Profile and hard filters

Two prompts. Do the profile extraction interactively — this is the step where your input
matters most.

```
Read my resume at ~/resume.pdf and generate config/profile.yaml per
SPEC.md §6.1. Include: skills with years and last-used and a verbatim evidence line
from the resume; seniority band; total relevant years; domains; and a
hard_constraints block I'll fill in myself.

Also generate 4 'profile documents' — short focused paragraphs for embedding
(what I do / core stack / domains / ideal role). Write them as prose, not bullets.

Show me the YAML before writing it. Flag anything you inferred rather than read.
```

Then edit it yourself. Fix the years, delete the skills you don't want to be hired for,
sharpen the ideal-role paragraph. Then:

```
Implement filters.py per SPEC.md §6.2.

- Pure functions, no I/O, no model calls. Each returns (passed: bool, reason: str|None).
- Filters: max_age_days, location allowlist, title blocklist, company blocklist,
  seniority band, salary floor (only when salary data exists — missing salary must
  NOT be a rejection), work-auth/clearance keywords.
- Every rejection is persisted with its reason so `jobs why <id>` can explain it.
- `jobs why <id>` prints: which filters it passed, which it failed and why, its scores
  if any, and its application status.
- Wire filters into the ingest pipeline as stage 4.

Tests: table-driven, one case per filter, plus a case proving missing salary passes.
```

**Done when:** `jobs why <id>` gives a straight answer for any job in the DB, and your board
isn't accidentally empty. If it is, the rejection reasons will tell you which filter to loosen.

---

## Phase 4 — Embeddings

```
Implement scoring/embed.py per SPEC.md §6.3.

- Ollama client hitting POST {OLLAMA_HOST}/api/embed with model from config
  (default nomic-embed-text). Batch inputs where the API allows.
- Cache vectors in the embeddings table keyed by content_hash + model. Never re-embed
  unchanged content. Store as packed float32 BLOB.
- Compute cosine similarity between each of my profile documents and each job
  description; persist max and mean.
- Plain numpy brute force over the vectors. Do NOT add sqlite-vec, faiss, chromadb,
  or any vector database — at a few thousand rows numpy is faster than the round trip.
- `jobs embed --limit N` and a `--stats` flag showing cache hit rate.

Test with a fake Ollama server via pytest-httpx. Include a test proving the cache
prevents a second call for identical content.
```

**Done when:** a second `jobs embed` run makes zero HTTP calls and prints 100% cache hits.

---

## Phase 5 — LLM rubric scoring (the phase to slow down on)

```
Implement scoring/rubric.py per SPEC.md §6.4.

- Pydantic models Subscores and JobScore exactly as specified.
- Call Ollama POST /api/chat with format=JobScore.model_json_schema() for structured
  output, temperature 0, stream false. Validate the response with
  JobScore.model_validate_json.
- The prompt must instruct the model to FIRST extract the job's explicit requirements
  and mark each required vs preferred, THEN evaluate each against the structured
  profile. Pass the structured profile from profile.yaml, not the raw resume text.
- score_total is computed in PYTHON as the sum of subscores. Never ask the model for
  a total and never let it override the sum.
- Validate that every string in `evidence` appears verbatim in the profile text.
  On failure, zero out that subscore's evidence, log a warning, and set a
  hallucination flag on the row.
- SCORER_VERSION constant = f"{SCHEMA_REV}:{model}:{PROMPT_REV}". Persist it on every
  job_scores row. Scoring skips jobs already scored at the current version.
- Only score the top N by embedding similarity among jobs that passed filters
  (N from config, default 40). Log which jobs were skipped and why.
- Retry once on schema-validation failure with a repair instruction; then give up
  and record a failure rather than writing a garbage score.
- `jobs score --limit N --force` and `jobs rescore --version-changed`.
```

Then, separately — this is the part people skip and regret:

```
Build the calibration harness, scoring/calibrate.py.

- tests/labeled_jobs.jsonl holds job descriptions plus my hand-assigned 0-100 scores.
- `jobs calibrate` scores them all with the current SCORER_VERSION and reports
  Spearman rho, mean absolute error, and the score distribution (I want to see the
  spread, not just the average).
- Print the 5 largest disagreements with the model's reasoning so I can see what it's
  getting wrong.
- Fail loudly if rho < 0.7.
```

Now do the work only you can do: pick 25 jobs already in your DB, read them, score each
0–100 by hand, and put them in `labeled_jobs.jsonl`. Then iterate on the prompt with
`jobs calibrate` as your feedback signal. Bump `PROMPT_REV` on every change.

**Done when:** ρ > 0.7, the score distribution actually spreads across the range rather than
bunching at 70–85, and the biggest disagreements are ones you can explain.

---

## Phase 6 — Application tracking

```
Implement application tracking per SPEC.md §5.4.

- Applications key on canonical_key, NOT job_id. This is the critical detail: it's
  what keeps a reposted req from resurfacing after I've applied.
- State machine with allowed transitions; reject invalid ones with a clear error.
  interested -> applied -> screening -> interview -> offer, plus rejected/withdrawn
  from any state, plus dismissed from any state.
- `interested` keeps the job VISIBLE on the board. Everything else hides it.
- Never delete application rows.
- service.py functions: list_jobs(sort, filters, include_hidden), get_job(id),
  set_status(canonical_key, status, notes), undo_last_action().
- CLI: `jobs apply <id>`, `jobs dismiss <id>`, `jobs interested <id>`, `jobs undo`,
  `jobs status <id> <state>`, `jobs list --sort score|date|blended`.
- Blended sort: score * exp(-age_days / 14).

Test specifically: mark applied, delete the job row, re-ingest the same posting with
a NEW source_job_id, confirm it does not appear on the default board.
```

**Done when:** that re-ingest test passes. It's the whole point of FR-8.

---

## Phase 7 — Web UI

```
Build the web UI per SPEC.md §8. FastAPI + Jinja2 + HTMX. No npm, no build step,
no React, no Tailwind CDN — plain CSS in one stylesheet.

- GET / — job board, default sort score desc, unactioned only.
- Sort toggle (date / score / blended), filters in a sidebar, all via HTMX partials.
- Each row: title, company, location, posted date, score badge, verdict, salary.
  Render inferred dates with a leading ~ and a title attribute explaining precision.
- Click a row to expand: subscores, matched requirements, gaps, evidence,
  description, and an Apply link opening the original ATS URL in a new tab.
- Action buttons post via HTMX and swap just that row. Include Undo.
- Health strip at the top: last run time, per-source status, new-job count.
- Bind to 127.0.0.1 only. No auth (Tailscale handles access).
- All routes call service.py. No SQL and no business logic in route handlers.
```

**Done when:** `jobs serve` and the board is usable at `http://127.0.0.1:8080` — sortable,
filterable, one-click actionable.

---

## Phase 8 — CLI polish + MCP server for Claude Code

This is what makes the board usable *from* Claude Code when you're applying — same session,
same host, no SSH round trip.

```
Add mcp_server.py exposing service.py over MCP (stdio transport, the official Python
MCP SDK). Tools:

- list_jobs(sort, min_score, max_age_days, limit, company_tag) -> compact JSON
- get_job(id) -> full detail including description, subscores, gaps, evidence
- mark_applied(id, notes), mark_dismissed(id, reason), mark_interested(id)
- search_jobs(query) -> keyword search over title/company/description
- pipeline_status() -> last run, per-source health, counts

Read-only tools must be side-effect free. Write tools return the new state so the
caller can confirm. Include a README section with the exact `claude mcp add` command.
```

Register it once:

```bash
claude mcp add jobboard -- ~/jobboard/.venv/bin/python -m jobboard.mcp_server
```

Now your applying workflow inside Claude Code becomes: *"Show me today's top 5 unactioned
matches, then open the first one and summarize what they want that my resume doesn't
already say."* Then, after you apply: *"Mark job 1423 applied."*

---

## Phase 9 — Put it on a schedule

The units run out of your working tree, so there's nothing to deploy — this phase is about
making unattended runs observable.

```
Write ops/ and the systemd user units per SPEC.md §7.

- ops/jobboard-ingest.service + .timer exactly as in SPEC.md §7.1, installed to
  ~/.config/systemd/user/. Use %h, not a hardcoded home path.
- ops/jobboard-web.service: uvicorn bound to 127.0.0.1:8080, Restart=always,
  also a user unit.
- ops/install-units.sh: copy the units, daemon-reload, enable both, print the next
  timer fire time. Idempotent — safe to re-run after edits.
- Nightly digest: after a run, write data/digest-YYYY-MM-DD.md with new-job count,
  top 5 by score, and per-source status. Optional ntfy.sh push, URL from env.
- Escalating alert: if any source has failed 3 consecutive runs, mark the digest
  DEGRADED and push regardless of whether there are new jobs.
- Drift alarm: if a company board returned >0 last run and 0 this run, log a warning
  and include it in the digest.
- Backup: sqlite3 .backup to data/backups/ before each run, keep the last 7.
- The ingest unit must set JOBBOARD_DB explicitly to data/jobs.db so it is never
  affected by whatever JOBBOARD_DB is exported in my interactive shell.
```

Then:

```bash
./ops/install-units.sh
systemctl --user start jobboard-ingest.service    # run once manually first
journalctl --user -u jobboard-ingest -f           # watch it
systemctl --user list-timers jobboard-ingest.timer
```

**Done when:** you log out, come back the next morning, and `journalctl --user -u
jobboard-ingest --since yesterday` shows a clean run with new scored jobs on the board.

One thing to verify explicitly, because it's the classic user-unit failure: log out entirely,
wait for a scheduled fire, and confirm it ran. If it didn't, `loginctl enable-linger` wasn't
applied.

---

## Ongoing operations

| Trigger | Action |
|---|---|
| An adapter returns 0 for a board that had jobs | Drift alarm fires; ask Claude Code to diff the live response against the stored fixture and fix the parser |
| You edit the rubric or swap models | Bump `PROMPT_REV`, run `jobs calibrate`, then `jobs rescore --version-changed` |
| Board feels empty | `jobs why <id>` on a few filtered-out jobs; loosen the offending filter |
| Board feels noisy | Tighten filters first, rubric second. Filters are free and deterministic. |
| Your resume changes | Regenerate `profile.yaml`, bump `PROMPT_REV`, rescore everything |
| New company to track | `jobs resolve <careers-url>` then re-ingest |
| You edited code today | Run `uv run pytest` before you stop — the timer fires against your working tree, so a broken commit is a lost night |
| Migration added | `alembic upgrade head` against `data/jobs.db`, not just your dev DB |

---

## Sensible v2 additions, in priority order

1. **Gap-driven resume suggestions** — you already store `unmet_requirements` per job.
   Aggregating those across your top 50 matches tells you exactly what to add to your resume,
   and it's the highest-value thing in this dataset that nobody builds.
2. **Company research enrichment** — funding, headcount trend, Glassdoor sentiment on the
   companies whose jobs score highest.
3. **Score-trend tracking** — watch how the market's demands shift across a job search.
4. **Cover-letter drafting** in Claude Code, grounded in the stored evidence and gaps.

Skip auto-apply. It's the most requested and least valuable automation in this space — the
success rate is poor, several ATS platforms treat it as abuse, and it's the one step where
your judgment is worth the most.
