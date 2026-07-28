"""Independent validation data sources.

Redundant fixture/result and market observations from providers OTHER than the
one the served engine uses, for reconciliation and SECONDARY market
benchmarking. Nothing here feeds ratings, predictions, or any served surface,
and nothing here writes `odds` or `market_odds_snapshots`.

Default OFF. See docs/VALIDATION-DATA-SOURCES.md.
"""
