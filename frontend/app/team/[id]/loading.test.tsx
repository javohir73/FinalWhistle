/** /team/[id] route skeleton: one status announcement; mirrors the crest banner
 *  and the max-w-3xl column so the profile drops in without shifting. */
import { render, screen } from "@testing-library/react";
import TeamLoading from "./loading";

it("announces a single 'Loading team…' status", () => {
  render(<TeamLoading />);
  expect(screen.getByRole("status")).toHaveAttribute("aria-label", "Loading team…");
});

it("keeps the page's max-w-3xl column so there is no layout shift", () => {
  const { container } = render(<TeamLoading />);
  expect(container.querySelector(".max-w-3xl")).toBeInTheDocument();
  expect(container.querySelectorAll(".skeleton").length).toBeGreaterThan(0);
});
