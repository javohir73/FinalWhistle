"""Sport-specific ingest adapters for the multi-sport vertical (NRL first).

Each module here is a self-contained feed adapter (fetch/parse/upsert) for one
sport, sharing the sport_* tables (app.models) via the `sport` discriminator
column. See task-2-brief.md.
"""
