import {
  ladderRowsToStandings,
  nrlExpectedMargin,
  nrlMatchHref,
  nrlMatchToSummary,
} from "@/lib/nrlAdapters";
import type { LadderRow, NrlMatch, NrlPrediction } from "@/lib/types";

const prediction = (over: Partial<NrlPrediction> = {}): NrlPrediction => ({
  p_home: 0.58, p_draw: 0.04, p_away: 0.38,
  expected_margin: 6.5, model_version: "nrl-v0.1", created_at: null,
  is_shadow: false, ...over,
});

const match = (over: Partial<NrlMatch> = {}): NrlMatch => ({
  id: 100, match_no: 1, kickoff_utc: "2026-07-18T06:00:00Z", venue: "Suncorp",
  home: "Broncos", away: "Storm", home_team_id: 1, away_team_id: 2,
  score_home: null, score_away: null, status: "scheduled",
  prediction: prediction(), ...over,
});

const ladderRow = (over: Partial<LadderRow> = {}): LadderRow => ({
  rank: 1, team_id: 1, name: "Storm", played: 20, wins: 16, draws: 0,
  losses: 4, points: 34, diff: 212, ...over,
});

describe("nrlMatchToSummary", () => {
  it("maps a scheduled match with a prediction: 3-way probs, no live/score fields", () => {
    const s = nrlMatchToSummary(match());
    expect(s.status).toBe("scheduled");
    expect(s.probabilities).toEqual({ home_win: 0.58, draw: 0.04, away_win: 0.38 });
    expect(s.predicted_winner).toBe("Broncos");
    expect(s.predicted_score).toBeNull();
    expect(s.confidence).toBeNull();
    expect(s.live_probabilities).toBeUndefined();
    expect(s.teams).toEqual({ home: "Broncos", away: "Storm" });
    expect(s.minute).toBeNull();
    expect(s.period).toBeNull();
    expect(s.goal_events).toEqual([]);
  });

  it("keeps the naturally-small draw segment rather than dropping it", () => {
    const s = nrlMatchToSummary(match({ prediction: prediction({ p_home: 0.62, p_draw: 0.02, p_away: 0.36 }) }));
    expect(s.probabilities?.draw).toBe(0.02);
  });

  it("has null probabilities and predicted_winner when the match is unpredicted", () => {
    const s = nrlMatchToSummary(match({ prediction: null }));
    expect(s.probabilities).toBeNull();
    expect(s.predicted_winner).toBeNull();
  });

  it("falls back to TBC for missing team names", () => {
    const s = nrlMatchToSummary(match({ home: null, away: null, prediction: null }));
    expect(s.teams).toEqual({ home: "TBC", away: "TBC" });
  });

  it("maps a finished match: status finished, scores carried through", () => {
    const s = nrlMatchToSummary(match({ status: "finished", score_home: 24, score_away: 12 }));
    expect(s.status).toBe("finished");
    expect(s.score_home).toBe(24);
    expect(s.score_away).toBe(12);
  });

  it("passes live status, score and minute to the shared scoreboard", () => {
    const s = nrlMatchToSummary(match({
      status: "in_play", minute: 42, score_home: 18, score_away: 12,
    }));
    expect(s.status).toBe("in_play");
    expect(s.minute).toBe(42);
    expect(s.score_home).toBe(18);
    expect(s.score_away).toBe(12);
  });
});

describe("nrlMatchHref", () => {
  it("returns the (season, round, match_no) URL when both are known", () => {
    expect(nrlMatchHref(2026, 20, 3)).toBe("/nrl/match/2026/20/3");
  });

  it("returns null when the round is still TBC", () => {
    expect(nrlMatchHref(2026, null, 3)).toBeNull();
  });

  it("returns null when the season is missing", () => {
    expect(nrlMatchHref(undefined, 20, 3)).toBeNull();
  });
});

describe("nrlExpectedMargin", () => {
  it("passes the model's expected margin through", () => {
    expect(nrlExpectedMargin(match())).toBe(6.5);
  });

  it("is null when the match carries no prediction", () => {
    expect(nrlExpectedMargin(match({ prediction: null }))).toBeNull();
  });

  it("is null when the prediction has no margin", () => {
    expect(nrlExpectedMargin(match({ prediction: prediction({ expected_margin: null }) }))).toBeNull();
  });
});

describe("ladderRowsToStandings", () => {
  it("carries rank/wins/losses/diff/points onto the shared row", () => {
    const [row] = ladderRowsToStandings([ladderRow({ rank: 6 })]);
    expect(row).toMatchObject({
      team_id: 1, team: "Storm", rank: 6, wins: 16, losses: 4, diff: 212,
      points: 34, projected_points: 34, projected_goal_diff: 212,
    });
  });

  it("threads the per-team top-8 projection into projection_pct", () => {
    const [row] = ladderRowsToStandings([ladderRow()], { Storm: { top8: 0.97, top4: 0.71 } });
    expect(row.projection_pct).toBe(0.97);
  });

  it("leaves projection_pct null when no projection is supplied for the team", () => {
    expect(ladderRowsToStandings([ladderRow()])[0].projection_pct).toBeNull();
    expect(ladderRowsToStandings([ladderRow()], { Panthers: { top8: 0.9, top4: 0.5 } })[0].projection_pct).toBeNull();
  });

  it("preserves the pre-sorted rank order so index+1 === rank", () => {
    const rows = ladderRowsToStandings([
      ladderRow({ rank: 1, team_id: 1, name: "Storm" }),
      ladderRow({ rank: 2, team_id: 2, name: "Panthers" }),
    ]);
    expect(rows.map((r) => r.team)).toEqual(["Storm", "Panthers"]);
  });
});
