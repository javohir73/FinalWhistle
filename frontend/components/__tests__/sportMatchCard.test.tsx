import { render, screen } from "@testing-library/react";
import { SportMatchCard } from "@/components/SportMatchCard";
import type { NrlMatch } from "@/lib/types";

const match: NrlMatch = {
  match_no: 3,
  kickoff_utc: "2026-07-11T09:35:00+00:00",
  venue: "Leichhardt Oval",
  home: "Wests Tigers",
  away: "Warriors",
  home_team_id: 17,
  away_team_id: 16,
  score_home: null,
  score_away: null,
  status: "scheduled",
  prediction: {
    p_home: 0.311,
    p_draw: 0.017,
    p_away: 0.672,
    expected_margin: -5.5,
    model_version: "nrl-elo-v0.1",
    created_at: "2026-07-06T00:00:00Z",
    is_shadow: true,
  },
};

it("links to the match detail page when season and round are known", () => {
  render(<SportMatchCard match={match} eyebrow="Round 19" season={2026} round={19} />);
  expect(screen.getByRole("link")).toHaveAttribute("href", "/nrl/match/2026/19/3");
  expect(screen.getByText("Warriors")).toBeInTheDocument();
});

it("renders a plain (unlinked) card when the round is unknown", () => {
  render(<SportMatchCard match={match} eyebrow="Round TBC" season={2026} round={null} />);
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
  expect(screen.getByText("Warriors")).toBeInTheDocument();
});
