# Live reliability & SLOs (engine roadmap, Phase 3)

The in-play engine reprices every match from the CURRENT score/minute/card state.
This doc formalizes the service levels it targets and the self-healing that was
already built to meet them — Phase 3's "reliability engineering: uptime SLOs,
feed-failure fallbacks (self-healing live state already exists — formalize it)."

## Latency budget: state change → new price < 5s

The re-price itself is a pure, stdlib Poisson-grid transform of values already
stored on the frozen prediction (`lambda_home`, `lambda_away`, `rho`) plus live
state. It is **sub-millisecond**:

| Measure (200 varied live-state snapshots, `time.perf_counter`) | Value |
|---|---|
| Mean per re-price | **0.19 ms** |
| Worst per re-price | **0.36 ms** |
| Budget (roadmap SLO) | 5000 ms |

Guarded by `backend/tests/test_live_latency.py` (asserts < 25 ms/call and < 1 s
for 200 calls — a >10⁴× margin on the 5s SLO). So the *computation* is never the
bottleneck.

The **user-visible** freshness is instead bounded by the data-refresh cadence:
a live score reaches the client on the next poll after ingestion. Stated
honestly, the SLO is **"< 5s from the latest successful score fetch to the
new price"**, which the math meets trivially; end-to-end freshness is the poll
cycle below (~60s worst case on the free tier), not the pricing.

## Live match state SLOs

- **Uptime:** 99.5% during active match dates — live state is available.
- **Freshness:** ≥ 90% of live scores reflected within ~2 minutes of provider
  availability (bounded by the 60s live-refresh rate limit + poll + network).
- **Post-results chain:** completes < 15 minutes after the final whistle
  (retry-with-backoff guarantees no finished match is orphaned).

## Self-healing already in place

These mechanisms exist in code and are what make the SLOs above achievable
without new infrastructure:

- **Monotonic freshness guard** (`pipeline/ingest/live_scores.py`): every match
  carries `provider_last_updated`; an incoming snapshot older than the stored one
  is ignored, and match state only ever moves `scheduled → in_play → finished`
  (never un-finished/un-lived from a lagging cache node). The DB stays consistent
  under provider lag.
- **Minute estimation** (`estimate_minute` / `_derive_period`): the free tier
  gives no live clock, so the minute is estimated from kickoff and the period
  label (HT / 2nd half / ET / PENS) is derived — the UI always shows a sensible
  clock (±2–3 min) even with no minute feed.
- **Opportunistic refresh** (`backend/app/live_refresh.py:maybe_refresh_live`):
  board/summary traffic and the every-minute `/api/live/ping` cron both schedule
  a rate-limited (60s), live-window-guarded refresh as a background task, so
  scores stay fresh during match windows without blocking any request.
- **Chain retry backoff** (`chain_status.py`, `LearningChainStatus`): the
  post-results learning chain records each attempt/failure and is retried with a
  ~10-minute backoff; `/api/health` surfaces `learning_chain` (pending,
  last_success_at, last_error) so a stuck chain is observable.
- **Cache invalidation:** a successful refresh (or chain completion) clears the
  per-match summary cache, so a stale price never outlives a score update.

## Feed-failure fallback

If the provider fetch fails (down / key expired / network error): the failure is
logged, the DB is left unchanged, and the score stays frozen at the last
successful fetch. Polling keeps retrying on the next 60s window, and the
post-results chain still runs off the last-seen score when the match finishes.
The in-play markets endpoint degrades gracefully: if the live clock/state is
unusable (extra-time, shootout, or no estimable minute), `GET
/v1/markets/{id}?live=1` falls back to the frozen pre-match markets
(`is_live: false`) rather than erroring.

## In-play market benchmark — blocked on a live odds feed

Phase 3's "benchmark vs in-play market snapshots" is **blocked on external
data**: neither the free live provider (football-data.org, match state only) nor
the pre-match odds source (api-sports `/odds`, populated ~48h pre-kickoff)
exposes in-play prices, and sharp live feeds (Pinnacle/Betfair) require a
commercial licence. Until such a feed is available, the model can only be
benchmarked against the **closing line** (the 90-minute snapshot, Phase 0/2).
When a live feed is obtained, capture in-play snapshots (minute-stamped) and
compare the re-priced W/D/L at minute *m* against the market at minute *m*.
