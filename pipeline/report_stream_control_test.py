from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import VenueMarket, VenuePriceTick
from pipeline.report_stream_control import stream_control_report


def test_stream_control_separates_transport_and_reports_parallel_coverage():
    now = datetime(2026, 7, 27, tzinfo=timezone.utc)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    market = VenueMarket(venue="polymarket", venue_key="P1", sport="football", market_type="match_winner", raw_title="A v B", mapping_status="mapped", status="open", first_seen=now, last_seen=now)
    db.add(market); db.flush()
    db.add_all([
        VenuePriceTick(venue_market_id=market.id, ts=now, source_ts=now - timedelta(milliseconds=50), transport="streaming", observation_key="event:1", raw_payload_ref="raw/1"),
        VenuePriceTick(venue_market_id=market.id, ts=now + timedelta(seconds=1), transport="polling", observation_key="cycle:1", raw_payload_ref="raw/2"),
    ])
    db.commit()
    report = stream_control_report(db, start=now - timedelta(seconds=1), end=now + timedelta(seconds=2))
    assert report["ticks_by_transport"] == {"polling": 1, "streaming": 1}
    assert report["markets_with_parallel_control"] == 1
    assert report["source_latency_ms"]["median"] == 50
