"""GET /api/retention — public device-level D7/D14 retention stats.

Anonymous device-day pings (app/api/activity.py) are the only signal: most
traffic never signs up (18 registered users total), so cohorts are keyed on
the client-generated device_id, not user_id. "since" is the WC26 final
(2026-07-19) — the day-zero anchor for the YC-application retention story
("D7 shown from Jul 26"). Cached like app/api/model_record.py (app.cache's
default TTL, 10 minutes) since this is a public, slow-moving read.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.cache import cache
from app.db import get_db
from app.models import DailyActivity

router = APIRouter(prefix="/api/retention", tags=["retention"])

# Day zero: the WC26 final. Every cohort/DAU row is anchored to this fixed
# date, never a moving "first deploy" timestamp, so the public numbers stay
# reproducible.
SINCE = date(2026, 7, 19)
_RETENTION_OFFSET_DAYS = (1, 7, 14)


def _today() -> date:
    """Seam for tests: cohort math is evaluated against "today" (to decide
    whether a d7/d14 checkpoint is even reachable yet), so tests monkeypatch
    this rather than depend on wall-clock date."""
    return datetime.now(timezone.utc).date()


def _daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


@router.get("")
def retention(db: Session = Depends(get_db)):
    cached = cache.get("retention:stats")
    if cached is not None:
        return cached

    today = _today()

    # First-ping day per device: a single GROUP BY query (never per-device),
    # the source of truth for both total_devices and cohort assignment (a
    # device that pings again later must not inflate a LATER day's cohort).
    first_ping: dict[str, date] = dict(
        db.query(DailyActivity.device_id, func.min(DailyActivity.day))
        .filter(DailyActivity.day >= SINCE)
        .group_by(DailyActivity.device_id)
        .all()
    )
    devices_by_cohort_day: dict[date, list[str]] = defaultdict(list)
    for device_id, first_day in first_ping.items():
        devices_by_cohort_day[first_day].append(device_id)
    cohort_sizes = Counter(first_ping.values())

    # Per-day distinct-device counts for DAU. UNIQUE(device_id, day) means
    # every row already represents exactly one device for that day, so a
    # plain per-day COUNT(*) IS the distinct-device count.
    day_counts: dict[date, int] = dict(
        db.query(DailyActivity.day, func.count())
        .filter(DailyActivity.day >= SINCE)
        .group_by(DailyActivity.day)
        .all()
    )

    # Per-device day membership, needed to check whether a SPECIFIC cohort's
    # devices came back on day+N (a per-day device count alone can't tell two
    # cohorts apart — see devices_by_cohort_day above). Date-arithmetic JOINs
    # (day + interval) render differently on SQLite vs Postgres, so the
    # portable choice is one query over the full (bounded-by-launch-date) row
    # set and an in-Python set-membership check, rather than N dialect-fragile
    # JOINs or a per-device/per-cohort query (avoids N+1 either way).
    activity_days: dict[str, set[date]] = defaultdict(set)
    for device_id, day in db.query(DailyActivity.device_id, DailyActivity.day).filter(
        DailyActivity.day >= SINCE
    ):
        activity_days[device_id].add(day)

    dau_start = max(SINCE, today - timedelta(days=29))
    dau = [
        {"day": d.isoformat(), "devices": day_counts.get(d, 0)}
        for d in _daterange(dau_start, today)
    ]

    cohorts = []
    for d in _daterange(SINCE, today):
        size = cohort_sizes.get(d, 0)
        cohort_devices = devices_by_cohort_day.get(d, [])
        row = {"day": d.isoformat(), "cohort_size": size}
        for n in _RETENTION_OFFSET_DAYS:
            target = d + timedelta(days=n)
            key = f"d{n}"
            # >= (not >): this is a public honesty surface, so a checkpoint
            # only shows a number once its UTC day has FULLY elapsed — a
            # same-day count would climb as more pings land and read as
            # final when it isn't (matches the page's "hasn't happened yet"
            # copy for the em dash).
            if size == 0 or target >= today:
                row[key] = None
            else:
                retained = sum(1 for dev in cohort_devices if target in activity_days.get(dev, ()))
                row[key] = round(100 * retained / size, 1)
        cohorts.append(row)

    out = {
        "since": SINCE.isoformat(),
        "total_devices": len(first_ping),
        "dau": dau,
        "cohorts": cohorts,
    }
    cache.set("retention:stats", out)
    return out
