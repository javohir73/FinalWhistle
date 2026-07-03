"""Latency proof for the Phase-3 in-play re-pricing (docs/ROADMAP-ENGINE.md).

The live markets endpoint (``GET /v1/markets/{id}?live=1``) re-prices every
market from the CURRENT match state on each request, so the SLO is a per-request
latency budget of < 5s. The cost is dominated by ``ml.models.live_markets`` —
one shared live grid plus its marginalizations — so this measures that directly
over 200 varied live-state snapshots and asserts a comfortable margin under the
budget.

Timing uses ``time.perf_counter`` (a monotonic clock — no wall-clock/Date.now
flakiness) and asserts both the aggregate and the worst single call.
"""
from __future__ import annotations

import time

from ml.models.live_markets import live_markets

# Stored engine params, mirroring the seeded prediction in test_markets_api.
LAM_HOME, LAM_AWAY, RHO = 1.7, 1.05, -0.03

#: Comfortable margin under the 5s per-request SLO. 200 full re-prices in under a
#: second means a single request (one re-price) has multiple orders of magnitude
#: of headroom.
TOTAL_BUDGET_S = 1.0
PER_CALL_BUDGET_S = 0.025  # 25 ms


def _snapshots(n: int = 200):
    """Varied but realistic live states: score, minutes remaining, and card
    counts sweep across their ranges so the timing covers the whole grid-size
    envelope (bigger current scores => bigger square grid)."""
    out = []
    for i in range(n):
        home = i % 4                      # 0..3 goals
        away = (i // 4) % 4               # 0..3 goals
        minutes_remaining = float(90 - (i % 91))   # 90..0
        red_home = (i // 7) % 2
        red_away = (i // 11) % 2
        yellow_home = i % 3
        yellow_away = (i // 2) % 3
        out.append((home, away, minutes_remaining,
                    red_home, red_away, yellow_home, yellow_away))
    return out


def test_live_repricing_is_well_under_the_latency_budget():
    snapshots = _snapshots(200)

    # Warm up import/JIT-free byte-compile so the measured loop is steady-state.
    live_markets(0, 0, LAM_HOME, LAM_AWAY, 90.0, rho=RHO)

    worst = 0.0
    start = time.perf_counter()
    for (h, a, rem, rh, ra, yh, ya) in snapshots:
        t0 = time.perf_counter()
        out = live_markets(
            h, a, LAM_HOME, LAM_AWAY, rem, rho=RHO,
            red_home=rh, red_away=ra, yellow_home=yh, yellow_away=ya,
        )
        worst = max(worst, time.perf_counter() - t0)
        # Every varied-but-valid snapshot must actually price (not fall back).
        assert out is not None
        assert set(out) == {
            "one_x_two", "double_chance", "totals", "btts",
            "correct_score", "asian_handicap",
        }
    total = time.perf_counter() - start

    assert total < TOTAL_BUDGET_S, (
        f"200 live re-prices took {total:.3f}s (budget {TOTAL_BUDGET_S}s)"
    )
    assert worst < PER_CALL_BUDGET_S, (
        f"slowest single re-price {worst * 1000:.2f}ms (budget "
        f"{PER_CALL_BUDGET_S * 1000:.0f}ms)"
    )
