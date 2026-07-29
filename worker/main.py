"""Process entry point for the polling capture worker.

Refuses to start unless capture is explicitly enabled AND an exact market
allowlist is supplied. Nothing here opens a socket at import time.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import signal
import threading

from worker.config import CaptureSettings

log = logging.getLogger(__name__)


def build_worker(settings: CaptureSettings, db):
    """Assemble the worker. Imported lazily so `-m worker.main --help`-style
    inspection and the refusal path never construct an HTTP session."""
    from pipeline.ingest.venues.kalshi import KalshiAdapter
    from pipeline.ingest.venues.polymarket import PolymarketAdapter
    from worker.capture import CaptureWorker
    from worker.raw_store import FileRawPayloadStore, S3RawPayloadStore

    adapters = {
        "kalshi": KalshiAdapter(timeout=settings.request_timeout_seconds),
        "polymarket": PolymarketAdapter(timeout=settings.request_timeout_seconds),
    }
    raw_store = (
        S3RawPayloadStore(
            bucket=settings.raw_store_bucket,
            endpoint_url=settings.raw_store_endpoint,
            region_name=settings.raw_store_region,
            max_payload_bytes=settings.max_raw_payload_bytes,
        )
        if settings.raw_store_backend == "s3"
        else FileRawPayloadStore(
            settings.raw_store_path, max_payload_bytes=settings.max_raw_payload_bytes
        )
    )
    return CaptureWorker(
        db=db,
        adapters={k: v for k, v in adapters.items() if k in settings.enabled_venues},
        raw_store=raw_store,
        settings=settings,
    )


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    settings = CaptureSettings.from_env()
    refusal = settings.refuse_reason()
    if refusal is not None:
        log.error("capture worker will not start: %s", refusal)
        return 2

    from app.db import SessionLocal

    stop = threading.Event()

    def request_stop(_signum, _frame) -> None:
        log.info("shutdown requested; current transaction will finish")
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    with SessionLocal() as db:
        worker = build_worker(settings, db)
        while not stop.is_set():
            cycle = datetime.now(timezone.utc).replace(microsecond=0)
            log.info("capture cycle starting", extra={"cycle": cycle.isoformat()})
            worker.run_all(scheduled_cycle_at=cycle)
            stop.wait(settings.inplay_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
