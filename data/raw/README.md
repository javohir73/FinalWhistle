# `data/raw/` — historical closing-odds CSVs

Drop bookmaker **closing-odds** CSVs for past World Cups here to run the
historical market benchmark (`docs/ROADMAP-ENGINE.md`, Phase 0). The closing
line, de-vigged, is the sharpest public predictor of match outcomes — the
benchmark answers the one question that decides the product: *do our
probabilities beat the market's?*

## CSV format

One row per match. Header (exact names, order does not matter):

```
date,home_team,away_team,odds_home,odds_draw,odds_away
2018-07-15,France,Croatia,1.95,3.60,4.10
2018-07-14,Belgium,England,2.05,3.40,3.90
```

| Column | Meaning |
|---|---|
| `date` | Match date, `YYYY-MM-DD` (parsed as ISO; time part, if any, is ignored). |
| `home_team`, `away_team` | Team names. Passed through `pipeline.team_mapping.normalize_team_name`, so source spellings ("Korea Republic", "IR Iran", "West Germany") are fine — add new aliases there if a join misses. On neutral World Cup venues the join also tries the swapped `(away, home)` orientation, so home/away order need not match the seeded results. |
| `odds_home`, `odds_draw`, `odds_away` | **Decimal** closing odds, each `> 1.0` (e.g. `1.95`). De-vigged to implied probabilities by proportional normalization. Fractional or American odds must be converted first. |

Malformed lines (missing a column, non-numeric odds) are **skipped with a
warning**, not fatal — the run continues on the rows that parse. Odds `<= 1.0`
raise in `devig`, so keep them strictly above 1.0.

## Running the benchmark

From the repo root:

```bash
PYTHONPATH=backend:. python -m pipeline.run_market_benchmark \
    --csv data/raw/wc2018_odds.csv --year 2018 \
    [--emit-json frontend/lib/market-benchmark-data.json]
```

The historical mode downloads the full international results history (martj42
mirror), replays Elo leak-free, predicts the target World Cup, joins the odds
from `--csv`, and prints a paired model-vs-market report. Use `--year 2022` with
a 2022 CSV. (Live WC26 mode is `--live` with `DATABASE_URL` set; no CSV.)
`--emit-json` additionally writes the page-ready result to
`frontend/lib/market-benchmark-data.json`, which the methodology page renders.

> The download step needs network. For an **offline**, network-free proof that
> the join/benchmark path works end to end, see
> `ml/evaluation/test_market_benchmark_historical.py`, which feeds a hand-built
> results DataFrame through the same pipeline using the committed sample below.

## Where to get closing odds (legitimate sources)

- **Kaggle World Cup odds datasets** — several community datasets carry 1X2
  closing/pre-match odds for WC 2018 and WC 2022. Export to the columns above.
- **OddsPortal** — historical closing odds per match (average or a named book);
  export/scrape into the CSV shape.
- **football-data.co.uk** — excellent free closing odds (`*CH/*CD/*CA` = closing
  home/draw/away), **but for domestic club leagues only** (EPL, La Liga, etc.).
  It does **not** cover the World Cup — use it for the Phase 1 club leagues, not
  here.

Always de-dupe against the seeded match dates/teams; a missed join shows up as
an "unmatched" warning naming the fixtures with no odds row.

## Committed sample vs. real data (gitignore)

`.gitignore` ignores real data dropped here (and data CSVs everywhere), while
explicitly keeping this README and the test fixture tracked:

```
data/raw/*                     # ignore real odds files dropped here
!data/raw/README.md            # …but keep this README tracked
*.csv                          # ignore data CSVs everywhere
!pipeline/data/*.csv           # …except pipeline seed CSVs
!ml/evaluation/fixtures/*.csv  # …and the committed benchmark fixture
```

So **real odds files you place in `data/raw/` are intentionally untracked** (they
can be large and are re-downloadable/derived). This README and the sample
fixture are un-ignored, so they commit normally — no `git add -f` needed.

The one **committed** sample — used by the offline test and as a format
reference — lives at `ml/evaluation/fixtures/wc2018_sample_odds.csv`. Keep it
small (a couple of real 2018 rows); it is a fixture, not a dataset.
