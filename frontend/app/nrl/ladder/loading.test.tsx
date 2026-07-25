/** /nrl/ladder route skeleton: one status announcement plus a glass ladder card
 *  reserving one row per club so the tabular box holds until the ladder lands. */
import { render, screen } from "@testing-library/react";
import NrlLadderLoading from "./loading";

it("announces a single 'Loading ladder…' status", () => {
  render(<NrlLadderLoading />);
  expect(screen.getByRole("status")).toHaveAttribute("aria-label", "Loading ladder…");
});

it("reserves one row per club (17) in the ladder card", () => {
  const { container } = render(<NrlLadderLoading />);
  // SkeletonRows rows carry `h-9`; the header bar does not — so counting h-9
  // blocks is an exact row count independent of the header/title blocks.
  expect(container.querySelectorAll(".skeleton.h-9")).toHaveLength(17);
});
