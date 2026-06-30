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

describe("regulation basis (90-min) + penalty shootouts", () => {
  it("group matches carry no 90-min basis and no shootout note", () => {
    const v = predictionVerdict(base);
    expect(v?.basis).toBeNull();
    expect(v?.shootout).toBeNull();
  });

  it("knockout matches are flagged as a 90-min prediction", () => {
    const v = predictionVerdict({ ...base, stage: "R16" });
    expect(v?.basis).toBe("90 min");
    expect(v?.shootout).toBeNull(); // decided in regulation, no shootout
  });

  it("a knockout level after 90 and decided on penalties keeps the exact-score hit and notes the shootout", () => {
    // Netherlands 1–1 Morocco (90'), Morocco win 3–2 on pens. AI predicted 1–1.
    const v = predictionVerdict({
      ...base,
      stage: "R32",
      teams: { home: "Netherlands", away: "Morocco" },
      score_home: 1,
      score_away: 1,
      penalty_home: 2,
      penalty_away: 3,
      predicted_score: { home: 1, away: 1, probability: 0.11 },
      probabilities: { home_win: 0.38, draw: 0.29, away_win: 0.33 },
    });
    expect(v?.kind).toBe("exact"); // the AI nailed the 90-min scoreline
    expect(v?.basis).toBe("90 min");
    expect(v?.shootout?.winner).toBe("Morocco");
    expect(v?.shootout?.text).toMatch(/penalties/i);
    expect(v?.shootout?.text).toContain("3");
    expect(v?.shootout?.text).toContain("2");
  });

  it("reads the shootout winner from the higher penalty tally (home win)", () => {
    const v = predictionVerdict({
      ...base,
      stage: "QF",
      teams: { home: "Brazil", away: "Japan" },
      score_home: 1,
      score_away: 1,
      penalty_home: 5,
      penalty_away: 4,
      predicted_score: { home: 2, away: 0, probability: 0.1 },
    });
    expect(v?.shootout?.winner).toBe("Brazil");
  });
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
