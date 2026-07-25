/** The broadcast Scorebug: a presentational header whose middle changes voice per
 *  status. Rendered directly (no data plumbing) so each state is asserted in
 *  isolation — the pre-match predicted score, the live pulse, the final result —
 *  plus the invariant that the W/D/L bar's aria-label carries the printed %s. */
import { render, screen } from "@testing-library/react";
import { Scorebug } from "@/components/Scorebug";
import type { Probabilities } from "@/lib/types";

const probs: Probabilities = { home_win: 0.55, draw: 0.25, away_win: 0.2 };

/** The bar's role="img" aria-label is the single accessible source of the %s. */
function expectBarLabelHasPercents() {
  const bar = screen.getByRole("img");
  const label = bar.getAttribute("aria-label") ?? "";
  expect(label).toMatch(/55%/);
  expect(label).toMatch(/25%/);
  expect(label).toMatch(/20%/);
}

test("upcoming: amber kickoff line, predicted score, and the caption", () => {
  render(
    <Scorebug
      competitionLabel="World Cup 26"
      home="Brazil"
      away="Croatia"
      homeTeamId={9}
      awayTeamId={10}
      status="upcoming"
      statusLine="8:00 PM · Estadio Azteca"
      predictedScore="2–1"
      probabilities={probs}
      teamBasePath="/football/wc26/team"
    />,
  );
  expect(screen.getByText("World Cup 26")).toBeInTheDocument();      // competition eyebrow
  expect(screen.getByText("8:00 PM · Estadio Azteca")).toBeInTheDocument();
  expect(screen.getByText("2–1")).toBeInTheDocument();               // most-likely scoreline
  expect(screen.getByText("MOST LIKELY SCORE")).toBeInTheDocument();
  expect(screen.queryByText("FULL TIME")).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "View Brazil profile" })).toHaveAttribute(
    "href",
    "/football/wc26/team/9",
  );
  expect(screen.getByRole("link", { name: "View Croatia profile" })).toHaveAttribute(
    "href",
    "/football/wc26/team/10",
  );
  expectBarLabelHasPercents();
});

test("live: rose LIVE clock with a pulsing dot (not animate-pulse), actual score", () => {
  const { container } = render(
    <Scorebug
      competitionLabel="World Cup 26"
      home="Brazil"
      away="Croatia"
      status="live"
      liveLabel="63'"
      venue="Emirates Stadium"
      score="1–0"
      probabilities={probs}
    />,
  );
  // Prototype live line is "LIVE · {clock} · {venue}" — the venue stays under the
  // lights after kickoff, not only pre-match.
  expect(screen.getByText(/LIVE.*63'.*Emirates Stadium/)).toBeInTheDocument();
  expect(screen.getByText("1–0")).toBeInTheDocument();
  // The pulse comes from the reduced-motion-gated status-live utilities, never
  // Tailwind's animate-pulse (which ignores prefers-reduced-motion).
  expect(container.querySelector(".status-live-dot")).toBeInTheDocument();
  expect(container.querySelector(".animate-pulse")).toBeNull();
  expect(screen.queryByText("MOST LIKELY SCORE")).not.toBeInTheDocument();
  expectBarLabelHasPercents();
});

test("live shootout: the level score plus the running spot-kick tally", () => {
  render(
    <Scorebug
      competitionLabel="World Cup 26"
      home="Brazil"
      away="Croatia"
      status="live"
      liveLabel="PENS"
      score="1–1"
      penaltyTally="5–4"
      probabilities={probs}
    />,
  );
  // The centre score stays level after 90/ET; the tally is the decisive number.
  expect(screen.getByText(/LIVE.*PENS/)).toBeInTheDocument();
  expect(screen.getByText("1–1")).toBeInTheDocument();
  expect(screen.getByText(/5–4 pens/)).toBeInTheDocument();
  expectBarLabelHasPercents();
});

test("ft: muted FULL TIME·venue and the final score", () => {
  render(
    <Scorebug
      competitionLabel="World Cup 26"
      home="Brazil"
      away="Croatia"
      status="ft"
      venue="Emirates Stadium"
      score="3–1"
      probabilities={probs}
    />,
  );
  // FULL TIME keeps the venue that always showed via the old LocalKickoff line.
  expect(screen.getByText("FULL TIME · Emirates Stadium")).toBeInTheDocument();
  expect(screen.getByText("3–1")).toBeInTheDocument();
  expect(screen.queryByText("MOST LIKELY SCORE")).not.toBeInTheDocument();
  expectBarLabelHasPercents();
});
