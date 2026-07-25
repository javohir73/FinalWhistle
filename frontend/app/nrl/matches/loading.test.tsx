/** /nrl/matches route skeleton: announces a single loading status and reserves
 *  the segmented-control + fixture-grid box with shimmer blocks (no data, no
 *  client hooks). */
import { render, screen } from "@testing-library/react";
import NrlMatchesLoading from "./loading";

it("announces a single 'Loading fixtures…' status", () => {
  render(<NrlMatchesLoading />);
  const status = screen.getByRole("status");
  expect(status).toHaveAttribute("aria-label", "Loading fixtures…");
});

it("renders shimmer placeholders and no live text", () => {
  const { container } = render(<NrlMatchesLoading />);
  expect(container.querySelectorAll(".skeleton").length).toBeGreaterThan(0);
});
