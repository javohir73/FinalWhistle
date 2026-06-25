import { render, screen } from "@testing-library/react";
import OfficialBracket from "@/components/OfficialBracket";
import { buildTree } from "@/lib/officialBracket";
import type { KnockoutTie } from "@/lib/types";

function tie(over: Partial<KnockoutTie>): KnockoutTie {
  return {
    match_no: 89,
    match_id: 1,
    stage: "R16",
    status: "scheduled",
    kickoff_utc: null,
    home: { team_id: null, team: null, score: null, penalty: null },
    away: { team_id: null, team: null, score: null, penalty: null },
    minute: null,
    period: null,
    injury_time: null,
    ...over,
  };
}

it("renders label-only ties as non-links with slot labels", () => {
  render(<OfficialBracket ties={buildTree(null)} />);
  expect(screen.getByText("Winner 74")).toBeInTheDocument();
  // a label-only tie has no /match link
  expect(document.querySelector('a[href^="/match/"]')).toBeNull();
});

it("renders a finished tie with score, pens text, winner highlight, and a link", () => {
  const ties = buildTree({
    ties: [
      tie({
        match_no: 89,
        match_id: 312,
        status: "finished",
        home: { team_id: 44, team: "Argentina", score: 1, penalty: 4 },
        away: { team_id: 51, team: "France", score: 1, penalty: 2 },
      }),
    ],
  });
  render(<OfficialBracket ties={ties} />);
  expect(screen.getByText("(4-2 pens)")).toBeInTheDocument();
  const link = document.querySelector('a[href="/match/312"]');
  expect(link).not.toBeNull();
  // winner side gets the lime-deep token; loser is muted
  const winner = screen.getByText("Argentina").closest("[data-side]");
  expect(winner?.className).toContain("text-lime-deep");
});

it("renders an in_play tie with a live badge and label", () => {
  const ties = buildTree({
    ties: [
      tie({
        match_no: 91,
        match_id: 330,
        status: "in_play",
        period: "second_half",
        minute: 57,
        home: { team_id: 44, team: "A", score: 1, penalty: null },
        away: { team_id: 51, team: "B", score: 0, penalty: null },
      }),
    ],
  });
  render(<OfficialBracket ties={ties} />);
  expect(screen.getByLabelText(/Live, 57'/)).toBeInTheDocument();
});

it("renders a mixed tie: real team on A, label on B", () => {
  const ties = buildTree({
    ties: [
      tie({
        match_no: 90,
        match_id: 320,
        status: "scheduled",
        home: { team_id: 44, team: "Argentina", score: null, penalty: null },
        away: { team_id: null, team: null, score: null, penalty: null },
      }),
    ],
  });
  render(<OfficialBracket ties={ties} />);
  expect(screen.getByText("Argentina")).toBeInTheDocument();
  expect(screen.getByText("Winner 75")).toBeInTheDocument();
});

it("renders the detached 3rd-place node", () => {
  render(<OfficialBracket ties={buildTree(null)} />);
  expect(screen.getByText("Loser 101")).toBeInTheDocument();
  expect(screen.getByRole("list", { name: /third place/i })).toBeInTheDocument();
});

it("exposes round lists with accessible names", () => {
  render(<OfficialBracket ties={buildTree(null)} />);
  expect(screen.getByRole("list", { name: "Round of 32" })).toBeInTheDocument();
  expect(screen.getByRole("list", { name: "Final" })).toBeInTheDocument();
});
