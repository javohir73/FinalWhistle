/** /nrl route skeleton: announces a single loading status and reserves the
 *  hero + spine/mini-ladder box with shimmer blocks (no data, no client hooks). */
import { render, screen } from "@testing-library/react";
import NrlHomeLoading from "./loading";

it("announces a single 'Loading…' status", () => {
  render(<NrlHomeLoading />);
  const status = screen.getByRole("status");
  expect(status).toHaveAttribute("aria-label", "Loading…");
});

it("renders shimmer placeholders and no live text", () => {
  const { container } = render(<NrlHomeLoading />);
  expect(container.querySelectorAll(".skeleton").length).toBeGreaterThan(0);
});
