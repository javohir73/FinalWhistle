# ADR 0001 — Research artifact delivery: Postgres, not the filesystem

**Status:** proposed (Phase 5A). **Date:** 2026-07-29.
**Scope:** the shadow research artifact only. Nothing about serving, capture,
or the model.

## The problem, stated exactly

`GET /api/research/market-benchmark` reads
`backend/app/research_data/market_benchmark.json` from the container
filesystem. In production that file can **never** exist:

1. `backend/Dockerfile` builds the image with `COPY backend /app/backend` —
   the filesystem is fixed at build time.
2. The artifact is gitignored (deliberately: generated data does not belong in
   git), so it is never in the build context.
3. `render.yaml` runs the API on the Render **free tier**, which has no
   persistent disk — anything written at runtime dies with the container, and
   there is no shell or cron to write it anyway.
4. The generator would run in GitHub Actions, whose runners are ephemeral and
   have no path into the running container.

So the endpoint's only reachable state in production is `no_data`, forever.
This is a delivery dead end, not a missing feature.

## Options considered

| Option | Verdict |
|---|---|
| Commit the artifact to git | Rejected. Generated data in git, frozen at image build, and every regeneration becomes a PR. |
| Object storage (S3/R2) | Rejected **for now**. Correct long-term for raw payloads, but needs credentials and a paid bucket → owner stop gate. Not required for aggregate JSON. |
| Render persistent disk | Rejected. Free tier does not offer one; upgrading is a spend decision. |
| **Postgres row** | **Chosen.** |

## Decision

Persist the artifact as a row in a new append-only `research_artifact` table,
read through a provider-neutral `ArtifactStore` boundary with two backends
(database, file).

Why this clears the dead end with nothing new: `DATABASE_URL` **already
exists on both sides** — Render injects it via `fromDatabase`, and GitHub
Actions already holds it as a secret used by `refresh.yml`, `market-intel.yml`
and `odds-snapshots.yml`. No new service, no new secret, no new cost, no new
vendor.

## What is deliberately NOT in this decision

- **Raw venue payloads stay out of the database.** They are large and
  unbounded; they keep their existing provenance path
  (`venue_price_tick.raw_payload_ref` → the raw store). The
  `MAX_ARTIFACT_BYTES` bound at the write boundary enforces that rather than
  trusting it. Durable raw-payload storage remains an open, stop-gated
  question and is untouched here.
- **Nothing is scheduled.** No workflow is added or enabled.
- **Nothing publishes by default.** `--publish-db` is opt-in and requires
  `--published-by`.

## Consequences

- The API gains a `db` dependency and reads database-first, file-second. A
  missing table is a **fallback**, not an error: this repo applies migrations
  through `refresh.yml` rather than on deploy, so between merge and the next
  migration run the table is absent — that window must read `no_data`, never
  500 on a public endpoint. Tested.
- The response gains a `source` field (`database` / `file`), so which backend
  answered is visible rather than inferred.
- The allowlist in `research.py` is unchanged and applies to **both**
  backends: publishing to the database is not a way around it. Tested with a
  poisoned row.
- Append-only with a `(kind, sha256)` uniqueness key: re-publishing identical
  content is a no-op, so replaying a run cannot grow the table. Reads take the
  latest by **generator** time, so a late publish of older content cannot
  displace newer content.

## Stop gates still standing

Enabling capture, provisioning object storage for raw payloads, adding any
schedule, and applying this migration to production (`refresh.yml` dispatch)
all remain owner decisions. This PR does none of them.
