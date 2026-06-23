/** MatchTabs: Overview is shown by default; the Lineups panel mounts only when
 *  its tab is opened (so the lineups island doesn't fetch until then). */
import { render, screen, fireEvent } from "@testing-library/react";
import { MatchTabs } from "@/components/MatchTabs";

it("shows Overview by default and lazy-mounts Lineups on tab click", () => {
  render(<MatchTabs overview={<p>overview-content</p>} lineups={<p>lineups-content</p>} />);

  // Overview is selected; its content shows; the lineups panel is NOT mounted yet.
  expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByText("overview-content")).toBeInTheDocument();
  expect(screen.queryByText("lineups-content")).not.toBeInTheDocument();

  // Switching to Lineups mounts its content and unmounts the overview.
  fireEvent.click(screen.getByRole("tab", { name: "Lineups" }));
  expect(screen.getByRole("tab", { name: "Lineups" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByText("lineups-content")).toBeInTheDocument();
  expect(screen.queryByText("overview-content")).not.toBeInTheDocument();
});
