# P0 operational review and safety correction — 2026-07-27

## Finding

The live smoke measured 349,101,242 response bytes for one complete two-venue
catalogue pass. At the former 15-minute discovery default, that implies about
936.36 GiB of catalogue responses and 218,880 discovery requests per 30-day
month from one worker, before any order-book calls.

The same catalogue exposed 46,433 active markets. Quoting every active market
would imply approximately 26,745,408 HTTP requests per day at the five-minute
pre-match cadence or 267,454,080 per day at the 30-second in-play cadence. This
is outside any acceptable shadow-capture budget and blocks an unfiltered
weekend run.

## Corrections

- Increased the default full-catalogue refresh from 15 minutes to 6 hours. At
  the observed payload size this reduces the projection to 9,120 discovery
  requests and about 39.02 GiB of catalogue responses per 30-day month.
- Added exact comma-separated `venue:venue_key` eligibility through
  `MARKET_CAPTURE_MARKET_KEYS`.
- Added a hard `MARKET_CAPTURE_MAX_MARKETS_PER_VENUE` ceiling, default 5, which
  bounds quote and settlement calls even if an allowlist is misconfigured.
- Added `MARKET_CAPTURE_REGISTRY_SCOPE=eligible` as the safe default so the first
  shadow cycle does not persist tens of thousands of non-selected discovery
  payloads. Full-catalogue registry persistence now requires explicit `all`.
  applies even when an allowlist supplies more keys.
- Quote and settlement calls now run only for the bounded eligible set. Every
  discovered market still receives a registry state.
- Unchanged discovery payloads are no longer rewritten on every cycle; a new
  raw discovery object is created for a new market or lifecycle/title/type/time
  change.
- Heartbeat-cycle results report markets seen, eligible, and skipped by policy.

With the hard ceiling alone, the theoretical request maximum becomes 5,760 per
day at five minutes or 57,600 per day at 30 seconds. The weekend run must use a
smaller exact match-market allowlist; the ceiling is a final guard, not the
primary eligibility policy.

## Verification

Focused configuration, capture, and raw-store tests passed: 24 tests. A
disposable PostgreSQL fixture rerun after the first correction produced six
registry markets, four ticks, two heartbeats, eleven raw objects, and no venue
errors. A controlled PostgreSQL-backed venue outage then produced an error
heartbeat for the failed venue while the healthy venue independently wrote one
registry market, one tick, one raw payload, and a successful heartbeat. No
production or paid resource was touched.

## Verdict

The unsafe unbounded remote-call behavior is corrected. A prospective weekend
run remains gated on selecting exact listed match-market keys and waiting for a
complete observation window.
