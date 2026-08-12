# CLAUDE.md — jobboard

Personal, single-user job board. Ingests postings from public ATS APIs, scores them against
my resume with a local Ollama model, and hides anything I've applied to or dismissed.

Full design in `SPEC.md`. Build plan in `BUILD_GUIDE.md`. When they conflict with your
instincts, they win — ask before deviating.

## Commands

```bash
uv sync                              # install
uv run jobs doctor                   # health check: DB, migrations, Ollama, config
uv run jobs ingest --all             # fetch from all enabled sources
uv run jobs score --limit 40         # LLM-score the top N by embedding similarity
uv run jobs run --all                # ingest + embed + score (what the timer runs)
uv run jobs list --sort score        # board in the terminal
uv run jobs why <id>                 # explain why a job is/isn't showing
uv run jobs calibrate                # score the labeled set, report correlation
uv run jobs serve                    # web UI on 127.0.0.1:8080
uv run pytest && uv run ruff check . && uv run mypy src/

systemctl --user list-timers jobboard-ingest.timer    # next scheduled run
systemctl --user start jobboard-ingest.service        # fire a run now
journalctl --user -u jobboard-ingest -n 100           # last run's output
```

## Architecture rules

- **`service.py` is the only business-logic entrypoint.** The CLI, the FastAPI routes, and
  the MCP server are thin adapters over it. No SQL in a route handler. No business logic in
  the CLI.
- **Adapters are isolated.** One module per source, implementing the `SourceAdapter`
  Protocol. A failing source records `status='partial'` on the run and never aborts the batch.
- **The pipeline is a funnel**: hard filters (free) → embeddings (cheap) → LLM rubric
  (expensive, top-N only). Never LLM-score the full crawl.
- **Everything is idempotent.** Running ingest twice must change nothing.

## Non-negotiable invariants

These have subtle failure modes. Don't "simplify" them.

1. **Date freezing.** For sources exposing only `updated_at` (Greenhouse), once a job is
   stored, never move `source_posted_at` later. A description edit must not push a
   three-month-old posting to the top of the board.
2. **`date_precision` is always set** — `exact` | `updated_only` | `inferred` — and surfaced
   in the UI. Never silently present an inferred date as a real one.
3. **Applications key on `canonical_key`, not `job_id`.** This is what stops a reposted req
   from resurfacing after I've applied. Application rows are never deleted.
4. **`score_total` is summed in Python from bounded subscores.** Never ask the model for a
   total, never let a model-supplied number override the sum. Asking an LLM for "a score out
   of 100" collapses the distribution to 72–85 and makes sorting meaningless.
5. **`evidence` strings must appear verbatim in the profile.** Validate in Python; flag the
   row on failure. This is the hallucination check.
6. **Every score row carries `scorer_version`.** Changing the model, schema, or prompt means
   bumping the version and rescoring — scores from different versions are not comparable.
7. **Adapter tests run offline** against fixtures in `tests/fixtures/`. Never hit a live API
   in the test suite.

## Do not add

Suggesting any of these means the design wasn't read:

- Vector databases (sqlite-vec, chroma, faiss, pinecone). NumPy brute force over a few
  thousand float32 vectors is faster than the round trip, and sqlite-vec is still pre-1.0.
- Docker Compose, Celery, Redis, RabbitMQ. A systemd timer running one Python process is the
  entire orchestration requirement.
- React, Next.js, npm, any build step. The UI is FastAPI + Jinja + HTMX.
- Postgres. SQLite with WAL is correct at this scale.
- Auth, user accounts, multi-tenancy. Single user, bound to localhost, accessed via Tailscale.
- Auto-submitting applications. Explicitly out of scope.
- Cloud LLM calls in the nightly path. Scoring is local Ollama only — my resume doesn't
  leave the box.

## Data handling

- `config/profile.yaml`, `config/companies.yaml`, `data/`, `*.db`, and any resume file are
  gitignored. Never commit them, never paste their contents into a commit message or a
  fixture.
- API keys (USAJOBS, Adzuna, ntfy) come from the environment. Never hardcode, never commit.
- Fixtures are real API responses — scrub anything identifying before saving.
- Respect `$JOBBOARD_DB`. Never hardcode a database path in application code; read it from
  config/env so dev and scheduled runs stay separated.

## Source policy

- **Tier 1 (default on):** public ATS endpoints — Greenhouse, Lever, Ashby, SmartRecruiters,
  Recruitee. Unauthenticated, publisher-intended, stable.
- **Tier 2 (on with a key):** USAJOBS, Adzuna, Remotive/RemoteOK. Honor attribution
  requirements and stay under free-tier limits.
- **Tier 3 (default off):** board scrapers via python-jobspy. Requires an explicit config
  opt-in. Jittered pacing, descriptive User-Agent, no credential storage, no cookie replay,
  no CAPTCHA handling, no authenticated-session scraping. If a site's terms prohibit
  automated access, it stays off.

## Runtime

Development and the scheduled run happen on the same Ubuntu host, out of this same checkout
(`~/jobboard`), alongside Ollama on loopback. There is no deploy step — a systemd **user**
timer runs `jobs run --all` against the working tree, so committed changes are live on the
next fire.

Consequences to keep in mind:

- **`data/jobs.db` is production.** It holds my real application history. For anything
  destructive — migrations, schema experiments, bulk deletes, reseeding — use the DB at
  `$JOBBOARD_DB`, which I set to `data/dev.db` during development. Ask before touching
  `data/jobs.db` directly.
- **Ollama and the ATS endpoints are live and reachable.** Prefer capturing a real response
  into `tests/fixtures/` and writing the parser against it over guessing the shape. Capture
  once; tests then run offline.
- **A broken commit breaks tonight's run.** Tests must pass before a session ends.
- The scheduled run is deterministic Python. Claude Code builds and maintains this pipeline;
  it is not part of the runtime.
