/** predictionVerdict: exact-score hit > right result > miss; null until FT. */
import { predictionVerdict, predictedOutcome } from "./verdict";
import type { MatchSummary } from "./types";

const base: MatchSummary = {
  match_id: 1,
  stage: "group",
  group: "Group A",
  kickoff_utc: null,
  venue: null,
  venue_city: null,
  venue_country: null,
  is_neutral: false,
  status: "finished",
  score_home: 2,
  score_away: 0,
  minute: null,
  period: null,
  injury_time: null,
  penalty_home: null,
  penalty_away: null,
  teams: { home: "Mexico", away: "South Africa" },
  predicted_winner: "Mexico",
  probabilities: { home_win: 0.6, draw: 0.25, away_win: 0.15 },
  predicted_score: { home: 1, away: 0, probability: 0.18 },
  confidence: "High",
  goal_events: [],
};

it("is null while a match is scheduled or in play", () => {
  expect(predictionVerdict({ ...base, status: "scheduled", score_home: null, score_away: null })).toBeNull();
  expect(predictionVerdict({ ...base, status: "in_play", score_home: 1, score_away: 0 })).toBeNull();
});

it("reports an exact-score hit", () => {
  const v = predictionVerdict({ ...base, predicted_score: { home: 2, away: 0, probability: 0.12 } });
  expect(v?.kind).toBe("exact");
});

it("reports a correct result when the scoreline differs", () => {
  expect(predictionVerdict(base)?.kind).toBe("winner"); // predicted 1–0, actual 2–0
});

it("reports a miss when the favoured outcome lost", () => {
  const v = predictionVerdict({ ...base, score_home: 0, score_away: 2 });
  expect(v?.kind).toBe("miss");
});

it("handles a predicted draw correctly", () => {
  const drawFavoured = { home_win: 0.2, draw: 0.55, away_win: 0.25 };
  expect(
    predictionVerdict({ ...base, probabilities: drawFavoured, score_home: 1, score_away: 1,
                        predicted_score: { home: 0, away: 0, probability: 0.2 } })?.kind,
  ).toBe("winner");
});

describe("predictedOutcome (AI prefill mapping)", () => {
  it("returns the argmax of the pre-match probabilities", () => {
    expect(predictedOutcome(base)).toBe("home"); // 0.60 / 0.25 / 0.15
    expect(predictedOutcome({ ...base, probabilities: { home_win: 0.2, draw: 0.5, away_win: 0.3 } })).toBe("draw");
    expect(predictedOutcome({ ...base, probabilities: { home_win: 0.1, draw: 0.3, away_win: 0.6 } })).toBe("away");
  });

  it("falls back to the named predicted_winner when probabilities are missing", () => {
    expect(predictedOutcome({ ...base, probabilities: null, predicted_winner: "Mexico" })).toBe("home");
    expect(predictedOutcome({ ...base, probabilities: null, predicted_winner: "South Africa" })).toBe("away");
  });

  it("is null when the model has no usable call", () => {
    expect(predictedOutcome({ ...base, probabilities: null, predicted_winner: null })).toBeNull();
    expect(predictedOutcome({ ...base, probabilities: null, predicted_winner: "Nowhere" })).toBeNull();
  });
});
