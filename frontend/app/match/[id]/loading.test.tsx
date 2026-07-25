/** /match/[id] route skeleton: the highest cold-start route. One status
 *  announcement; mirrors the max-w-2xl column, the scoreboard hero and the
 *  Overview/Lineups tab strip so the match centre swaps in without shifting. */
import { render, screen } from "@testing-library/react";
import MatchLoading from "./loading";

it("announces a single 'Loading match…' status", () => {
  render(<MatchLoading />);
  expect(screen.getByRole("status")).toHaveAttribute("aria-label", "Loading match…");
});

it("keeps the page's max-w-2xl column so there is no layout shift", () => {
  const { container } = render(<MatchLoading />);
  expect(container.querySelector(".max-w-2xl")).toBeInTheDocument();
  expect(container.querySelectorAll(".skeleton").length).toBeGreaterThan(0);
});
