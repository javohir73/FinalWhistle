/** Flag chip: shows the self-hosted flag image, and falls back to a clean
 *  initials chip instead of the browser's broken-image "?" when a flag can't
 *  load (unmapped team or a stray error). */
import { render, screen, fireEvent } from "@testing-library/react";
import { Flag } from "@/components/Flag";

function flagImg(): HTMLImageElement | null {
  return document.querySelector("img");
}

it("renders the self-hosted flag image for a known team", () => {
  render(<Flag team="Brazil" />);
  const img = flagImg();
  expect(img).not.toBeNull();
  expect(img!.getAttribute("src")).toBe("/flags/br.png");
});

it("uses the flagcdn subdivision codes for England/Scotland", () => {
  render(<Flag team="England" />);
  expect(flagImg()!.getAttribute("src")).toBe("/flags/gb-eng.png");
});

it("falls back to initials if the flag errors — never a broken image", () => {
  render(<Flag team="South Korea" />);
  fireEvent.error(flagImg()!); // image load fails → typographic fallback

  expect(flagImg()).toBeNull(); // no broken <img> left behind
  expect(screen.getByText("SK")).toBeInTheDocument(); // typographic chip
});

it("uses the initials chip directly for an unknown team (no image)", () => {
  render(<Flag team="Atlantis" />);
  expect(flagImg()).toBeNull();
  expect(screen.getByText("A")).toBeInTheDocument();
});
