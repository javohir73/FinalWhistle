import { render, screen } from "@testing-library/react";
import { GoalMarkets } from "@/components/GoalMarkets";
import type { GoalMarkets as GoalMarketsData } from "@/lib/types";

function markets(p4 = 0.4): GoalMarketsData {
  return {
    home: { to_score: 0.86, p2: 0.6, p3: 0.45, p4 },
    away: { to_score: 0.39, p2: 0.12, p3: 0.03, p4: 0.01 },
    total: { over_1_5: 0.78, over_2_5: 0.55, over_3_5: 0.3 },
    btts: 0.34,
  };
}

it("renders per-team bands, totals and BTTS", () => {
  render(<GoalMarkets home="Argentina" away="Cape Verde" markets={markets()} />);
  expect(screen.getByText("Argentina")).toBeInTheDocument();
  expect(screen.getByText("Cape Verde")).toBeInTheDocument();
  expect(screen.getByText("Over 2.5")).toBeInTheDocument();
  expect(screen.getByText("Both score")).toBeInTheDocument();
});

it("shows the 4+ band only when notable (p4 >= 0.10)", () => {
  const { rerender } = render(
    <GoalMarkets home="Argentina" away="Cape Verde" markets={markets(0.4)} />,
  );
  expect(screen.getByText("4+ goals")).toBeInTheDocument();

  rerender(<GoalMarkets home="Argentina" away="Cape Verde" markets={markets(0.02)} />);
  expect(screen.queryByText("4+ goals")).not.toBeInTheDocument();
});
