/** Flag chip: shows the flag image, recovers a transient CDN failure with one
 *  retry, and falls back to a clean initials chip instead of the browser's
 *  broken-image "?" when the flag truly can't load. */
import { render, screen, fireEvent } from "@testing-library/react";
import { Flag } from "@/components/Flag";

function flagImg(): HTMLImageElement | null {
  return document.querySelector("img");
}

it("renders the flag image for a known team", () => {
  render(<Flag team="Brazil" />);
  const img = flagImg();
  expect(img).not.toBeNull();
  expect(img!.getAttribute("src")).toBe("https://flagcdn.com/w80/br.png");
});

it("retries once (cache-busted) before giving up", () => {
  render(<Flag team="Argentina" />);
  const img = flagImg()!;
  expect(img.getAttribute("src")).toBe("https://flagcdn.com/w80/ar.png");

  // First failure → cache-busted retry, still an <img> (the flag may load now).
  fireEvent.error(img);
  const retry = flagImg();
  expect(retry).not.toBeNull();
  expect(retry!.getAttribute("src")).toBe("https://flagcdn.com/w80/ar.png?r=1");
});

it("falls back to initials after both attempts fail — never a broken image", () => {
  render(<Flag team="South Korea" />);
  fireEvent.error(flagImg()!); // attempt 0 fails → retry
  fireEvent.error(flagImg()!); // retry fails → fallback

  expect(flagImg()).toBeNull(); // no broken <img> left behind
  expect(screen.getByText("SK")).toBeInTheDocument(); // typographic chip
});

it("uses the initials chip directly for an unknown team (no image)", () => {
  render(<Flag team="Atlantis" />);
  expect(flagImg()).toBeNull();
  expect(screen.getByText("A")).toBeInTheDocument();
});
