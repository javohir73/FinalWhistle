/** WinProbTimeline (Floodlight P4 slice p4-s1): the match centre's win-probability
 *  chart. For football it renders the model's PRE-MATCH forecast trajectory as a
 *  pure, server-renderable SVG (role="img" with a printed-% aria-label as the
 *  accessible source of truth), degrading to an honest single hero bar when there
 *  is no trajectory yet — never a fabricated minute-by-minute chart. */
import { render, screen } from "@testing-library/react";
import { WinProbTimeline } from "@/components/WinProbTimeline";
import type { ProbHistoryPoint, Probabilities } from "@/lib/types";

const PROBS: Probabilities = { home_win: 0.62, draw: 0.24, away_win: 0.14 };

function makePoints(homeSeries: number[], withDates = true): ProbHistoryPoint[] {
  return homeSeries.map((p_home, i) => ({
    date: withDates ? `2026-07-${String(i + 1).padStart(2, "0")}` : null,
    p_home,
    p_draw: (1 - p_home) / 2,
    p_away: (1 - p_home) / 2,
  }));
}

describe("WinProbTimeline", () => {
  it("renders an svg[role=img] with the printed current % in its aria-label and a trajectory path", () => {
    const { container } = render(
      <WinProbTimeline
        points={makePoints([0.5, 0.55, 0.6, 0.66])}
        probabilities={PROBS}
        homeLabel="Brazil"
        awayLabel="Uruguay"
      />,
    );

    const svg = screen.getByRole("img");
    expect(svg.tagName.toLowerCase()).toBe("svg");
    // The printed current % (last p_home = 66%) is the accessible source of truth.
    expect(svg).toHaveAttribute("aria-label", expect.stringContaining("66%"));
    expect(svg).toHaveAttribute("aria-label", expect.stringContaining("Brazil"));

    // A real trajectory path is drawn (not the fallback bar).
    const path = container.querySelector("path");
    expect(path).not.toBeNull();
    expect(path).toHaveAttribute("d", expect.stringContaining("M"));
  });

  it("degrades to the honest hero bar (no trajectory) when there are <2 points", () => {
    const { container } = render(
      <WinProbTimeline
        points={makePoints([0.62])}
        probabilities={PROBS}
        homeLabel="Brazil"
        awayLabel="Uruguay"
      />,
    );

    // The single role="img" is the W/D/L bar, carrying its printed-% aria-label.
    const bar = screen.getByRole("img");
    expect(bar).toHaveAttribute("aria-label", expect.stringContaining("62%"));
    expect(bar).toHaveAttribute("aria-label", expect.stringContaining("draw 24%"));

    // The honest copy, and NO fabricated chart.
    expect(screen.getByText("Forecast movement appears once the model updates this fixture.")).toBeInTheDocument();
    expect(container.querySelector("path")).toBeNull();
  });

  it("draws one marker circle per marker, on top of the current-point dot", () => {
    const { container } = render(
      <WinProbTimeline
        points={makePoints([0.5, 0.55, 0.6, 0.66])}
        probabilities={PROBS}
        homeLabel="Brazil"
        awayLabel="Uruguay"
        markers={[
          { at: 0.25, tone: "home" },
          { at: 0.6, tone: "away" },
        ]}
      />,
    );

    // Two markers + the always-present current-point dot.
    const circles = container.querySelectorAll("circle");
    expect(circles).toHaveLength(3);
    // Marker tone maps to the ring color, never fill/color alone.
    expect(container.querySelector("circle.stroke-loss")).not.toBeNull();
  });

  it("still renders the honest single-bar state for an empty points array — never throws or fakes a chart", () => {
    const { container } = render(
      <WinProbTimeline
        points={[]}
        probabilities={PROBS}
        homeLabel="Brazil"
        awayLabel="Uruguay"
      />,
    );

    expect(screen.getByRole("img")).toHaveAttribute("aria-label", expect.stringContaining("62%"));
    expect(screen.getByText("Forecast movement appears once the model updates this fixture.")).toBeInTheDocument();
    expect(container.querySelector("path")).toBeNull();
    expect(container.querySelector("svg")).toBeNull();
  });
});
