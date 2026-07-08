/** ModelVsMarket: the model-vs-market W/D/L section on the match page. */
import { render, screen } from "@testing-library/react";
import { ModelVsMarket } from "./ModelVsMarket";
import type { Prediction } from "@/lib/types";

const base = {
  match_id: 99,
  probabilities: { home_win: 0.25, draw: 0.29, away_win: 0.46 },
} as unknown as Prediction;

describe("ModelVsMarket", () => {
  it("shows both triples when a market snapshot exists", () => {
    const p = {
      ...base,
      odds_comparison: {
        available: true,
        market: { home_win: 0.22, draw: 0.27, away_win: 0.51 },
        captured_at: "2026-07-08T10:00:00+00:00",
      },
    } as Prediction;
    render(<ModelVsMarket prediction={p} home="Norway" away="England" />);
    expect(screen.getByText("Model vs market")).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: "Norway win 25%, draw 29%, England win 46%" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: "Norway win 22%, draw 27%, England win 51%" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Not betting advice/)).toBeInTheDocument();
  });

  it("renders nothing without a snapshot", () => {
    const p = { ...base, odds_comparison: { available: false } } as Prediction;
    const { container } = render(
      <ModelVsMarket prediction={p} home="Norway" away="England" />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
