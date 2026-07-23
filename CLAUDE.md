# CLAUDE.md — fifa-wc26-prediction

How to work in this repo. Global rules live in `~/.claude/CLAUDE.md`; this file adds
the repo-specific rules and the model lane. When they conflict, this file wins.

## Default posture

- Work runs silent by default. When you have enough to act, act — don't narrate
  options you won't pursue or re-litigate settled decisions.
- Match the surrounding code: naming, comment density, and idiom of the file you're in.
- Report outcomes faithfully. If tests fail, say so with the output. No success
  claims without evidence.

## The stop gate

Run without interrupting **until an action is hard to undo or faces outward.** Then
stop, show a plain-English summary built from the actual diff or command, and wait
for an explicit "go". This is one rule, not a fixed number of check-ins. It fires on:

- **Spending money** — provisioning paid resources, anything that incurs cost.
- **Shipping to production** — merging to `main`, a Render/Vercel deploy, or running
  `refresh.yml` against the prod database.
- **Destructive / irreversible ops** — `git push --force`, history rewrites, `rm -rf`,
  dropping tables, `alembic downgrade`.
- **Sending outward** — emails, external API writes, posting to any third party.

Everything reversible and internal — reads, local edits, feature branches, running
the test suite — needs no check-in. Run it.

## Model lane

Route work to the cheapest model that can do it; escalate only for judgment or stakes.
The human sets the tier per session — honor it, and when spawning subagents pick their
model to match:

- **Haiku** — reads, lookups, mechanical search.
- **Sonnet** — building, editing, running tests. The default worker.
- **Opus** — planning, code review, judging, hard debugging.
- **Fable** — top tier only: design/architecture, production debugging, security,
  migrations. ~20% of the work, max. Reaching for it is a spend decision → confirm
  first (stop gate).

## Test gate

Before claiming work is done or opening a PR, run the real suite and paste the output:

- Everything: `make test`
- Python only: `.venv/bin/python -m pytest` (testpaths: `backend`, `ml`, `pipeline`;
  files are `*_test.py` / `test_*.py`)
- Frontend: `cd frontend && npm run typecheck && npm run lint && npm test`

## The guarded pipeline

`branch → PR → CI → [stop: summary + "go"] → merge to main → deploy → verify`

- Merging to `main` stays behind the stop gate: show the plain-English summary,
  wait for the human's explicit "go" — then Claude merges the PR itself
  (CI must be green first).
- CI runs via `.github/workflows/ci.yml`.
- Backend auto-deploys to Render from `main` (`render.yaml`); frontend deploys to
  Vercel (see `DEPLOYMENT.md`).
- After a deploy, verify: `GET /api/health` on the prod API, then spot-check the
  behavior you changed.

## Database migrations — sequencing matters

Render's free tier has no pre-deploy step, so **migrations do not run on deploy.**
They run via the `refresh.yml` GitHub Action (`alembic upgrade head`). Therefore a
migration must reach the prod DB *before* the code that depends on it goes live, or
the API 500s. For any schema change:

1. Merge the migration.
2. Dispatch `refresh.yml` (applies `alembic upgrade head`) and confirm it succeeded.
3. Only then is the dependent code path safe to serve.

This touches prod and is hard to undo → it goes through the stop gate.

## Degraded mode

If your assigned model is unavailable, drop one tier (Fable → Opus → Sonnet → Haiku)
and say so in your first message. For anything that would hit the stop gate, don't
silently substitute — stop and ask before continuing.

## Repo gotchas

- `pitchprophet-*` names (Render service/DB, prod API host) are **legacy but
  load-bearing** — they map to live resources. Do not rename.
- The repo is **private**. Never push code, logs, or data to a public destination.
- Model version string: `poisson-elo-v0.5` (`ml/models/model_params.json`).

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. When in doubt, invoke the skill.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Strategy/scope → invoke /plan-ceo-review
- Architecture → invoke /plan-eng-review
- Design system/plan review → invoke /design-consultation or /plan-design-review
- Full review pipeline → invoke /autoplan
- Bugs/errors → invoke /investigate
- QA/testing site behavior → invoke /qa or /qa-only
- Code review/diff check → invoke /review
- Visual polish → invoke /design-review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
- Save progress → invoke /context-save
- Resume context → invoke /context-restore
- Author a backlog-ready spec/issue → invoke /spec
