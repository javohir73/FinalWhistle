"""Process entry point for the polling capture worker."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import signal
import threading

from app.db import SessionLocal
from pipeline.ingest.venues.kalshi import KalshiAdapter
from pipeline.ingest.venues.polymarket import PolymarketAdapter
from worker.capture import CaptureWorker
from worker.config import CaptureSettings
from worker.raw_store import FileRawPayloadStore, S3RawPayloadStore

log = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = CaptureSettings.from_env()
    stop = threading.Event()

    def request_stop(_signum, _frame) -> None:
        log.info("shutdown requested; current transaction will finish")
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    adapters = {
        "kalshi": KalshiAdapter(timeout=settings.request_timeout_seconds),
        "polymarket": PolymarketAdapter(timeout=settings.request_timeout_seconds),
    }
    raw_store = (
        S3RawPayloadStore(
            bucket=settings.raw_store_bucket,
            endpoint_url=settings.raw_store_endpoint,
            region_name=settings.raw_store_region,
        )
        if settings.raw_store_backend == "s3"
        else FileRawPayloadStore(settings.raw_store_path)
    )
    with SessionLocal() as db:
        worker = CaptureWorker(
            db=db,
            adapters=adapters,
            raw_store=raw_store,
            settings=settings,
        )
        while not stop.is_set():
            cycle = datetime.now(timezone.utc).replace(microsecond=0)
            log.info("capture cycle starting", extra={"cycle": cycle.isoformat()})
            worker.run_all(scheduled_cycle_at=cycle)
            stop.wait(settings.inplay_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
