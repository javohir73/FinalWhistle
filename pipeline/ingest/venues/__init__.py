"""Transport-neutral contracts for prediction-market venue adapters.

Contracts only. No adapter, no I/O, no capture. Adapters land on top of this
package; nothing here reaches a network or a table.
"""

from pipeline.ingest.venues.redaction import looks_like_credential, redact
from pipeline.ingest.venues.types import (
    UNSUPPORTED_IN_PLAY,
    DiscoveryResult,
    HeartbeatIdentity,
    InPlayState,
    OrderBook,
    OrderBookLevel,
    Quote,
    RawDocument,
    RejectedPayload,
    Settlement,
    TickIdentity,
    VenueAdapter,
    VenueMarket,
    VenuePayloadError,
    heartbeat_identity,
    tick_identity,
)

__all__ = [
    "UNSUPPORTED_IN_PLAY",
    "DiscoveryResult",
    "HeartbeatIdentity",
    "InPlayState",
    "OrderBook",
    "OrderBookLevel",
    "Quote",
    "RawDocument",
    "RejectedPayload",
    "Settlement",
    "TickIdentity",
    "VenueAdapter",
    "VenueMarket",
    "VenuePayloadError",
    "heartbeat_identity",
    "looks_like_credential",
    "redact",
    "tick_identity",
]
