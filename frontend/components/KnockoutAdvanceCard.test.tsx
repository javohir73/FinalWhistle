/** KnockoutAdvanceCard: the "Who goes through" advance bar + route split for
 *  an upcoming knockout tie. */
import { render, screen } from "@testing-library/react";
import { KnockoutAdvanceCard } from "./KnockoutAdvanceCard";
import type { KnockoutAdvance } from "@/lib/types";

const block: KnockoutAdvance = {
  p_advance_home: 0.39,
  p_advance_away: 0.61,
  p_extra_time: 0.29,
  p_shootout: 0.17,
  paths: {
    home: { win_90: 0.25, win_et: 0.06, win_pens: 0.08 },
    away: { win_90: 0.46, win_et: 0.07, win_pens: 0.08 },
  },
};

describe("KnockoutAdvanceCard", () => {
  it("shows both advance probabilities and the route split", () => {
    render(<KnockoutAdvanceCard knockout={block} home="Norway" away="England" />);
    expect(screen.getByText(/who goes through/i)).toBeInTheDocument();
    expect(screen.getByText("Norway 39%")).toBeInTheDocument();
    expect(screen.getByText("England 61%")).toBeInTheDocument();
    expect(screen.getByText("in 90 minutes")).toBeInTheDocument();
    expect(screen.getByText("in extra time")).toBeInTheDocument();
    expect(screen.getByText("on penalties")).toBeInTheDocument();
  });

  it("explains the tie-level extra-time and shootout chances", () => {
    render(<KnockoutAdvanceCard knockout={block} home="Norway" away="England" />);
    expect(
      screen.getByText(/29% chance this tie needs extra time, 17% that it reaches penalties/),
    ).toBeInTheDocument();
  });

  it("labels the advance bar for screen readers", () => {
    render(<KnockoutAdvanceCard knockout={block} home="Norway" away="England" />);
    expect(
      screen.getByRole("img", { name: "Norway advance 39%, England advance 61%" }),
    ).toBeInTheDocument();
  });
});
