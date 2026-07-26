"""Read-only CLI for the complete NRL pre-match evaluation harness.

Usage:
    PYTHONPATH=backend:. python -m pipeline.sports.nrl_evaluate \
      --from-season 2023 --to-season 2025 \
      --model-version nrl-score-v0.1-shadow
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import logging
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from ml.sports.nrl.evaluation import EvaluationConfig, evaluate

log = logging.getLogger(__name__)

SPORT = "nrl"
TEAM_NAME_ALIASES = {"Tigers": "Wests Tigers"}


def _read_only_snapshot(db: Session) -> None:
    """Pin one repeatable, read-only transaction when PostgreSQL supports it."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))


def load_matches(db: Session) -> tuple[list[dict], dict]:
    """Load and canonicalize finished NRL fixtures without mutating the DB."""
    from app.models import SportMatch, SportTeam

    teams = db.query(SportTeam.id, SportTeam.name).filter_by(sport=SPORT).all()
    name_to_id = {name: team_id for team_id, name in teams}
    id_aliases: dict[int, int] = {}
    applied_aliases: list[dict] = []
    for source_name, target_name in TEAM_NAME_ALIASES.items():
        source_id = name_to_id.get(source_name)
        target_id = name_to_id.get(target_name)
        if source_id is None:
            continue
        if target_id is None:
            raise ValueError(
                f"canonical target {target_name!r} is missing for alias {source_name!r}"
            )
        id_aliases[source_id] = target_id
        applied_aliases.append(
            {
                "source_name": source_name,
                "source_id": source_id,
                "target_name": target_name,
                "target_id": target_id,
            }
        )

    matches = (
        db.query(SportMatch)
        .filter_by(sport=SPORT, status="finished")
        .order_by(SportMatch.kickoff_utc.asc(), SportMatch.id.asc())
        .all()
    )
    rows = [
        {
            "match_id": match.id,
            "season": match.season,
            "round": match.round,
            "kickoff_utc": match.kickoff_utc,
            "venue": match.venue,
            "home_team_id": id_aliases.get(match.home_team_id, match.home_team_id),
            "away_team_id": id_aliases.get(match.away_team_id, match.away_team_id),
            "score_home": match.score_home,
            "score_away": match.score_away,
        }
        for match in matches
    ]
    inventory = {
        "source_rows": len(rows),
        "team_count_before_aliases": len(teams),
        "canonical_aliases": applied_aliases,
        "market_source": None,
        "market_reason": "production contains no licensed NRL closing-line archive",
    }
    return rows, inventory


def _json_text(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _json_line(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _fmt(value: object, digits: int = 4) -> str:
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return html.escape(str(value))


def _table(headers: list[str], rows: list[list[object]]) -> str:
    head = "".join(f"<th>{html.escape(header)}</th>" for header in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{_fmt(value)}</td>" for value in row) + "</tr>"
        for row in rows
    )
    return (
        f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>"
    )


def _reliability_svg(points: list[dict]) -> str:
    width = height = 320
    pad = 38
    scale = width - 2 * pad
    circles = []
    path = []
    for point in points:
        x = pad + float(point["mean_predicted"]) * scale
        y = height - pad - float(point["empirical_freq"]) * scale
        path.append(f"{x:.1f},{y:.1f}")
        radius = min(8.0, 2.5 + float(point["count"]) ** 0.5 / 3)
        circles.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}"><title>'
            f'n={point["count"]}</title></circle>'
        )
    polyline = " ".join(path)
    return f"""<svg viewBox="0 0 {width} {height}" role="img" aria-label="Winner probability reliability diagram">
      <line class="axis" x1="{pad}" y1="{height-pad}" x2="{width-pad}" y2="{height-pad}"/>
      <line class="axis" x1="{pad}" y1="{height-pad}" x2="{pad}" y2="{pad}"/>
      <line class="ideal" x1="{pad}" y1="{height-pad}" x2="{width-pad}" y2="{pad}"/>
      <polyline class="curve" points="{polyline}"/>{''.join(circles)}
      <text x="{width/2}" y="{height-5}" text-anchor="middle">Predicted probability</text>
      <text x="12" y="{height/2}" text-anchor="middle" transform="rotate(-90 12 {height/2})">Observed frequency</text>
    </svg>"""


def render_report(payload: dict) -> str:
    results = payload["results"]
    gates = results["gates"]
    paired = results["paired_comparisons"]
    winner = results["winner"]
    margin = results["margin"]
    total = results["total"]
    scoreline = results["scoreline"]
    noise = paired["winner_log_loss_vs_elo_favorite"]["noise_floor"]

    gate_rows = []
    comparison_key = {
        "winner": "winner_log_loss_vs_elo_favorite",
        "margin": "margin_mae_vs_elo",
        "total": "total_mae_vs_rolling",
        "scoreline": "scoreline_mae_vs_rolling",
    }
    for name in ("winner", "margin", "total", "scoreline"):
        gate = gates[name]
        ci = paired[comparison_key[name]]["ci95"]
        gate_rows.append(
            [
                name.title(),
                "PASS" if gate["passed"] else "FAIL",
                f'{100 * gate["improvement"]:.2f}%',
                f"[{ci[0]:.4f}, {ci[1]:.4f}]",
                f'{gate["seasons_improved"]}/{len(results["seasons"])}',
            ]
        )

    winner_rows = [
        [
            key,
            values["log_loss"],
            values["brier"],
            values["rps"],
            values["accuracy"],
            values["ece"],
        ]
        for key, values in winner.items()
    ]
    margin_rows = [
        [
            key,
            values["mae"],
            values["rmse"],
            values["bias"],
            values["winner_sign_accuracy"],
        ]
        for key, values in margin.items()
    ]
    total_rows = [
        [key, values["mae"], values["rmse"], values["bias"], values["within_6"]]
        for key, values in total.items()
    ]
    score_rows = [
        [
            key,
            values["home_mae"],
            values["away_mae"],
            values["combined_team_mae"],
            values["exact_hit_rate"],
            values["both_within_6"],
        ]
        for key, values in scoreline.items()
    ]
    season_rows = []
    for season, values in results["by_season"].items():
        season_rows.append(
            [
                season,
                values["n"],
                values["winner"]["model"]["log_loss"],
                values["winner"]["elo_favorite"]["log_loss"],
                values["margin"]["model"]["mae"],
                values["margin"]["elo"]["mae"],
                values["total"]["model"]["mae"],
                values["total"]["rolling"]["mae"],
                values["scoreline"]["model"]["combined_team_mae"],
                values["scoreline"]["rolling_home_away"]["combined_team_mae"],
            ]
        )
    markets = results["market_benchmarks"]
    market_rows = []
    for name, value in markets.items():
        coverage = ", ".join(
            f'{season}: {100 * detail["coverage"]:.0f}%'
            for season, detail in value["by_season"].items()
        )
        metrics = value["metrics"]
        if metrics is None:
            headline = "—"
        elif name == "moneyline":
            headline = f'log loss {metrics["log_loss"]:.4f}'
        else:
            headline = f'MAE {metrics["mae"]:.4f}'
        market_rows.append(
            [name, value["status"], coverage, headline, value["blocker"] or "—"]
        )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>FinalWhistle NRL evaluation</title>
<style>
:root{{--bg:#07130e;--panel:#0d1d15;--line:#254130;--text:#edf8f0;--muted:#9ab4a1;--accent:#9aef29;--danger:#ff6d78}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,sans-serif}}
main{{max-width:1120px;margin:auto;padding:40px 24px 80px}} h1{{font-size:42px;margin:0 0 8px}} h2{{margin-top:42px}}
.lede,.muted{{color:var(--muted)}} .notice{{border:1px solid var(--line);background:var(--panel);padding:16px 18px;border-radius:12px}}
table{{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line)}} th,td{{padding:10px 12px;border-bottom:1px solid var(--line);text-align:right}} th:first-child,td:first-child{{text-align:left}} th{{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.06em}}
.table-wrap{{max-width:100%;overflow-x:auto}}
.grid{{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:24px;align-items:start}} svg{{width:100%;background:var(--panel);border:1px solid var(--line);border-radius:12px}} svg text{{fill:var(--muted);font-size:11px}} .axis{{stroke:var(--muted)}} .ideal{{stroke:var(--line);stroke-dasharray:5 5}} .curve{{fill:none;stroke:var(--accent);stroke-width:2}} circle{{fill:var(--accent)}}
@media(max-width:760px){{.grid{{grid-template-columns:1fr}} table{{font-size:12px}} th,td{{padding:8px}}}}
</style></head><body><main>
<p class="muted">FINALWHISTLE · READ-ONLY WALK-FORWARD EVALUATION</p><h1>NRL model report</h1>
<p class="lede">{results["n"]} held-out matches across {', '.join(map(str, results["seasons"]))}. Lower loss and error values are better.</p>
<div class="notice"><strong>Noise floor:</strong> on this sample, winner log-loss differences smaller than approximately {_fmt(noise)} are not distinguishable from round-cluster variation at 95%.</div>
<h2>Independent promotion gates</h2>{_table(["Component","Gate","Improvement","Paired 95% CI","Seasons better"], gate_rows)}
<div class="grid"><div><h2>Winner probabilities</h2>{_table(["Model","Log loss","Brier","RPS","Accuracy","ECE"], winner_rows)}</div><div><h2>Reliability</h2>{_reliability_svg(results["calibration"]["reliability"])}</div></div>
<h2>Margin</h2>{_table(["Model","MAE","RMSE","Bias","Winner sign"], margin_rows)}
<h2>Total points</h2>{_table(["Model","MAE","RMSE","Bias","Within 6"], total_rows)}
<h2>Team scores</h2>{_table(["Model","Home MAE","Away MAE","Combined MAE","Exact hit","Both within 6"], score_rows)}
<p class="muted">Exact score hits are diagnostic only; they are too sparse to control promotion.</p>
<h2>Held-out seasons</h2>{_table(["Season","N","Winner LL","Favourite LL","Margin MAE","Elo margin","Total MAE","Rolling total","Team-score MAE","Rolling team scores"], season_rows)}
<h2>Market benchmarks</h2>{_table(["Market","Status","Coverage","Headline metric","Reason"], market_rows)}
<p class="muted">Dataset fingerprint: {html.escape(payload["dataset_fingerprint"])}</p>
</main></body></html>"""


def write_artifacts(
    evaluation: dict,
    inventory: dict,
    output_root: Path,
    *,
    generated_at: datetime | None = None,
) -> Path:
    config = evaluation["config"]
    safe_version = re.sub(r"[^a-zA-Z0-9._-]+", "-", config["model_version"])
    run_id = (
        f"{safe_version}-{config['from_season']}-{config['to_season']}-"
        f"{evaluation['dataset_fingerprint'][:12]}"
    )
    output_dir = output_root / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    predictions_path = output_dir / "predictions.jsonl"
    predictions_path.write_text(
        "\n".join(_json_line(row) for row in evaluation["predictions"]) + "\n",
        encoding="utf-8",
    )
    results_payload = {
        "dataset_fingerprint": evaluation["dataset_fingerprint"],
        "config": config,
        "score_params": evaluation["score_params"],
        "winner_params_by_season": evaluation["winner_params_by_season"],
        "results": evaluation["results"],
    }
    results_path = output_dir / "results.json"
    results_path.write_text(_json_text(results_payload), encoding="utf-8")

    audit = dict(evaluation["leakage_audit"])
    audit["canonical_aliases"] = inventory["canonical_aliases"]
    audit["source_rows"] = inventory["source_rows"]
    audit_path = output_dir / "leakage_audit.json"
    audit_path.write_text(_json_text(audit), encoding="utf-8")

    report_path = output_dir / "report.html"
    report_path.write_text(render_report(results_payload), encoding="utf-8")

    timestamp = generated_at or datetime.now(timezone.utc)
    manifest = {
        "model_version": config["model_version"],
        "dataset_fingerprint": evaluation["dataset_fingerprint"],
        "code_commit": _git_commit(),
        "generated_at": timestamp.isoformat(),
        "seed": config["seed"],
        "bootstrap_samples": config["bootstrap_samples"],
        "evaluation_config": config,
        "score_params": evaluation["score_params"],
        "winner_params_by_season": evaluation["winner_params_by_season"],
        "database_mode": "read-only repeatable-read snapshot",
        "inventory": inventory,
        "artifacts": {
            path.name: _sha256(path)
            for path in (predictions_path, results_path, audit_path, report_path)
        },
    }
    (output_dir / "manifest.json").write_text(_json_text(manifest), encoding="utf-8")
    return output_dir


def run(
    db: Session,
    config: EvaluationConfig,
    output_root: Path,
    *,
    generated_at: datetime | None = None,
) -> tuple[dict, Path]:
    _read_only_snapshot(db)
    rows, inventory = load_matches(db)
    evaluation = evaluate(rows, config)
    output_dir = write_artifacts(
        evaluation,
        inventory,
        output_root,
        generated_at=generated_at,
    )
    return evaluation, output_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-season", type=int, default=2023)
    parser.add_argument("--to-season", type=int, default=2025)
    parser.add_argument("--model-version", required=True)
    parser.add_argument("--bootstrap-samples", type=int, default=10_000)
    parser.add_argument(
        "--output-root", type=Path, default=Path("artifacts/nrl_backtests")
    )
    parser.add_argument("--require-gates", action="store_true")
    args = parser.parse_args()
    if args.from_season > args.to_season:
        parser.error("--from-season must be <= --to-season")
    if args.bootstrap_samples < 1:
        parser.error("--bootstrap-samples must be positive")

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    config = EvaluationConfig(
        from_season=args.from_season,
        to_season=args.to_season,
        model_version=args.model_version,
        bootstrap_samples=args.bootstrap_samples,
    )
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        evaluation, output_dir = run(db, config, args.output_root)
    finally:
        db.close()
    gates = evaluation["results"]["gates"]
    for name in ("winner", "margin", "total", "scoreline"):
        gate = gates[name]
        log.info(
            "%s: %s (improvement %.2f%%, seasons %d/%d)",
            name,
            "PASS" if gate["passed"] else "FAIL",
            100 * gate["improvement"],
            gate["seasons_improved"],
            len(config.held_out_seasons),
        )
    log.info("artifacts: %s", output_dir)
    if args.require_gates and not all(gate["passed"] for gate in gates.values()):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
