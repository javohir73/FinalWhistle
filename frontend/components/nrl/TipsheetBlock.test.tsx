import { render, screen } from "@testing-library/react";
import { TipsheetBlock } from "./TipsheetBlock";
import type { NrlTipsheet, NrlTipsheetMatch } from "@/lib/types";

function match(overrides: Partial<NrlTipsheetMatch> = {}): NrlTipsheetMatch {
  return {
    id: 1, match_no: 1, kickoff_utc: "2026-03-12T00:00:00+00:00",
    venue: "AAMI Park", home: "Storm", away: "Eels",
    home_team_id: 1, away_team_id: 2, score_home: null, score_away: null,
    status: "scheduled", prediction: null,
    ...overrides,
  };
}

const tipsheet = (overrides: Partial<NrlTipsheet> = {}): NrlTipsheet => ({
  season: 2026,
  round: 2,
  matches: [],
  record: {
    evaluated_matches: 12, winner_accuracy: 0.75, winner_accuracy_ci95: [0.45, 0.92],
    avg_log_loss: 0.52, avg_brier: 0.31, best_streak: 4, last_updated: "2026-07-20T10:00:00+00:00",
  },
  worst_miss: null,
  disclaimer: "For analytics and entertainment only. Not betting advice.",
  ...overrides,
});

it("flags the biggest lock and closest call across the round's picks", () => {
  const lock = match({
    match_no: 1, home: "Storm", away: "Eels",
    prediction: { p_home: 0.82, p_draw: 0.01, p_away: 0.17, expected_margin: 12, model_version: "v1", created_at: "2026-03-01T00:00:00+00:00", is_shadow: false, pick: "home", pick_confidence: 0.82 },
  });
  const close = match({
    match_no: 2, home: "Broncos", away: "Titans",
    prediction: { p_home: 0.51, p_draw: 0.02, p_away: 0.47, expected_margin: 1, model_version: "v1", created_at: "2026-03-01T00:00:00+00:00", is_shadow: false, pick: "home", pick_confidence: 0.51 },
  });
  render(<TipsheetBlock tipsheet={tipsheet({ matches: [lock, close] })} />);

  expect(screen.getByText("Biggest lock")).toBeInTheDocument();
  expect(screen.getByText("Closest call")).toBeInTheDocument();
  expect(screen.getByText("Pick: Storm · 82%")).toBeInTheDocument();
  expect(screen.getByText("Pick: Broncos · 51%")).toBeInTheDocument();
});

it("does not flag a closest call when only one match has a prediction", () => {
  const only = match({
    prediction: { p_home: 0.6, p_draw: 0.01, p_away: 0.39, expected_margin: 3, model_version: "v1", created_at: "2026-03-01T00:00:00+00:00", is_shadow: false, pick: "home", pick_confidence: 0.6 },
  });
  render(<TipsheetBlock tipsheet={tipsheet({ matches: [only] })} />);

  expect(screen.getByText("Biggest lock")).toBeInTheDocument();
  expect(screen.queryByText("Closest call")).not.toBeInTheDocument();
});

it("shows the arriving-before-kickoff state for a match with no prediction yet", () => {
  render(<TipsheetBlock tipsheet={tipsheet({ matches: [match({ prediction: null })] })} />);
  expect(screen.getByText("Prediction arriving before kickoff.")).toBeInTheDocument();
});

it("shows the result next to the locked pick for a finished match", () => {
  const finished = match({
    status: "finished", score_home: 12, score_away: 24,
    prediction: { p_home: 0.8, p_draw: 0.01, p_away: 0.19, expected_margin: 8, model_version: "v1", created_at: "2026-03-01T00:00:00+00:00", is_shadow: false, pick: "home", pick_confidence: 0.8 },
  });
  render(<TipsheetBlock tipsheet={tipsheet({ matches: [finished] })} />);

  expect(screen.getByText("Full time")).toBeInTheDocument();
  expect(screen.getByText("12")).toBeInTheDocument();
  expect(screen.getByText("24")).toBeInTheDocument();
  expect(screen.getByText(/Picked Storm \(80%\) — missed it/)).toBeInTheDocument();
});

it("renders nothing for worst_miss when the round hasn't graded a miss", () => {
  render(<TipsheetBlock tipsheet={tipsheet({ matches: [match()], worst_miss: null })} />);
  expect(screen.queryByText(/worst miss/)).not.toBeInTheDocument();
});

it("states the worst miss plainly when present", () => {
  render(
    <TipsheetBlock
      tipsheet={tipsheet({
        matches: [match()],
        worst_miss: {
          season: 2026, round: 1, home: "Storm", away: "Eels",
          score_home: 12, score_away: 24, pick: "home", pick_team: "Storm",
          pick_probability: 0.8, winner: "away", winner_team: "Eels",
        },
      })}
    />,
  );
  expect(screen.getByText(/Last round's worst miss:/)).toBeInTheDocument();
  expect(screen.getByText(/picked Storm \(80%\)/)).toBeInTheDocument();
});

it("shows a Live badge for a match inside its kickoff window", () => {
  const kickoff = new Date(Date.now() - 30 * 60_000).toISOString();
  const live = match({ kickoff_utc: kickoff, prediction: null });
  render(<TipsheetBlock tipsheet={tipsheet({ matches: [live] })} />);
  expect(screen.getByText("Live")).toBeInTheDocument();
});

it("never states accuracy without its N", () => {
  render(<TipsheetBlock tipsheet={tipsheet({ matches: [match()] })} />);
  expect(screen.getByText(/12 graded/)).toBeInTheDocument();
});

it("shows the no-graded-matches state when the season record is still empty", () => {
  render(
    <TipsheetBlock
      tipsheet={tipsheet({
        matches: [match()],
        record: {
          evaluated_matches: 0, winner_accuracy: null, winner_accuracy_ci95: null,
          avg_log_loss: null, avg_brier: null, best_streak: 0, last_updated: null,
        },
      })}
    />,
  );
  expect(screen.getByText(/No graded matches yet this season/)).toBeInTheDocument();
});
