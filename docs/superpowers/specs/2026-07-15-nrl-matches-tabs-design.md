# NRL Fixtures Page — WC26-Style Tabs — Design

**Date:** 2026-07-15
**Status:** Approved (brainstorm 2026-07-15; user chose "WC26 tabs, NRL rounds")

## Summary

Rework `/nrl/matches` from a flat ascending round list into the WC26 fixtures
UX: a segmented **Upcoming / Live / Finished** control with live games pinned
on top — adapted to NRL's round structure (round groups, not calendar-day
buckets).

## Non-goals

- No team search box, no day bucketing (user explicitly chose the round
  variant over the exact WC26 clone).
- No API changes: `/api/nrl/matches` already carries everything needed.
- No changes to `SportMatchCard`, the match-detail live view, or Origin.

## Design

1. **Structure** — `frontend/app/nrl/matches/page.tsx` becomes a thin server
   wrapper (SSR fetch via `getNrlMatchesServer`, first paint keeps SEO and
   the 300s ISR), rendering a new client island
   `frontend/app/nrl/matches/MatchesClient.tsx` that owns filter state —
   mirroring `frontend/app/matches/{page.tsx,MatchesClient.tsx}`.
2. **Tabs** — Upcoming (default) / Live / Finished:
   - *Upcoming*: `status == "scheduled"` and not in the live window, grouped
     by round ascending, kickoff ascending within a round.
   - *Finished*: `status == "finished"`, grouped by round **descending**
     (latest results first), kickoff descending within a round.
   - *Live*: matches in the live window only.
   - Like WC26, live matches are also pinned in a strip at the top of the
     Upcoming view with a LIVE badge; the Finished view never shows them.
3. **Live detection** — the NRL list API only has `scheduled`/`finished`, so
   "live" is derived: `status != "finished"` AND `kickoff_utc <= now <
   kickoff_utc + LIVE_WINDOW`. `LIVE_WINDOW` follows the football
   `isLiveNow` convention (~2h — NRL games run ~100 minutes). The helper is
   a pure function so it unit-tests without a clock dependency (now injected).
4. **Refresh while live** — in-window scores land in the DB via the existing
   15-minute `nrl-live-refresh` poller. The island refetches the fixtures
   list every 60s **only while** at least one match is in its live window
   (client fetch through the existing `/backend-api` rewrite); otherwise no
   polling.
5. **Empty states** — per-tab copy mirroring WC26's ("No matches are live
   right now.", "No finished fixtures yet.", "No upcoming fixtures yet.").
6. **Testing** — pure unit tests for the live-window + grouping helpers;
   component test for tab switching, round ordering (asc/desc per tab), and
   the pinned live strip; frontend gates (typecheck, lint, jest).

## Rollout

Feature branch → PR → CI → stop gate ("go") → merge → Vercel deploy →
verify `/nrl/matches` on prod during and outside a live window.
