"""Machine-checked promotion gate over an availability_record payload.

Deliberately dependency-free (stdlib only, no app/ml imports) so
shadow-record.yml can import it with a bare `actions/setup-python` and no
backend install — the daily odds-twin readout must not depend on that
install succeeding. Kept separate from pipeline/run_availability_benchmark.py,
which pulls in the DB/ML stack to build the record this function scores.
"""
from __future__ import annotations


def availability_gate(record: dict, min_n: int = 20) -> dict:
    """Machine-checked promotion gate over an availability_record payload.

    met iff n_matches >= min_n AND diff_ci95 is a valid 2-list/tuple with its
    upper bound < 0 (availability credibly ahead of production on log-loss —
    same CI convention as _verdict: diff = availability - production, so a
    negative upper bound means availability wins across the whole interval).
    Never raises on the honest-empty shape (n_matches: 0, diff_ci95: None)."""
    n = record.get("n_matches", 0) or 0
    ci = record.get("diff_ci95")
    delta = record.get("diff_log_loss")
    if not ci or len(ci) != 2:
        return {"met": False, "n": n, "min_n": min_n, "delta_log_loss": delta,
                "reason": "insufficient record"}
    if n < min_n:
        return {"met": False, "n": n, "min_n": min_n, "delta_log_loss": delta,
                "reason": f"n below min_n ({n} < {min_n})"}
    if ci[1] >= 0:
        return {"met": False, "n": n, "min_n": min_n, "delta_log_loss": delta,
                "reason": "CI straddles zero"}
    return {"met": True, "n": n, "min_n": min_n, "delta_log_loss": delta,
            "reason": "met: availability credibly ahead"}
