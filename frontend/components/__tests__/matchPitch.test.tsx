/** MatchPitch: both starting XIs on one shared pitch — home on the top half
 *  (GK at the very top), away on the bottom half (GK at the very bottom),
 *  mirrored around the centre line. Display-only (no ratings/photos). */
import { render, screen, fireEvent } from "@testing-library/react";
import { MatchPitch } from "@/components/MatchPitch";
import type { TeamLineup } from "@/lib/types";

const home: TeamLineup = {
  team: "Brazil",
  formation: "4-3-3",
  coach: "Tite",
  start_xi: [
    { name: "Alisson", number: 1, position: "G", grid: "1:1", is_starter: true },
    { name: "Marquinhos", number: 4, position: "D", grid: "2:2", is_starter: true },
    { name: "Vinicius Junior", number: 10, position: "F", grid: "4:1", is_starter: true },
  ],
  bench: [],
};

const away: TeamLineup = {
  team: "Croatia",
  formation: "4-2-3-1",
  coach: "Dalic",
  start_xi: [
    { name: "Livakovic", number: 1, position: "G", grid: "1:1", is_starter: true },
    { name: "Modric", number: 10, position: "M", grid: "3:2", is_starter: true },
  ],
  bench: [],
};

it("renders both teams on one shared pitch with names + formation labels", () => {
  render(<MatchPitch home={home} away={away} />);

  expect(screen.getByRole("group", { name: /Brazil versus Croatia/i })).toBeInTheDocument();
  expect(screen.getByText("Brazil")).toBeInTheDocument();
  expect(screen.getByText("Croatia")).toBeInTheDocument();
  expect(screen.getByText("4-3-3")).toBeInTheDocument();
  expect(screen.getByText("4-2-3-1")).toBeInTheDocument();
  // Every starter is a labelled, keyboard-accessible button.
  expect(screen.getByRole("button", { name: /#10 Vinicius Junior \(F\)/ })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /#10 Modric \(M\)/ })).toBeInTheDocument();
});

it("places the home GK at the top and the away GK at the bottom (mirrored halves)", () => {
  render(<MatchPitch home={home} away={away} />);
  const labels = screen.getAllByRole("button").map((b) => b.getAttribute("aria-label") || "");

  // Home GK is the first shirt (top); away GK is the last shirt (bottom).
  expect(labels[0]).toContain("Alisson");
  expect(labels[labels.length - 1]).toContain("Livakovic");
  // …and the home GK precedes the away GK in the DOM.
  expect(labels.findIndex((l) => l.includes("Alisson"))).toBeLessThan(
    labels.findIndex((l) => l.includes("Livakovic")),
  );
});

it("toggles a player's detail on tap", () => {
  render(<MatchPitch home={home} away={away} />);
  const btn = screen.getByRole("button", { name: /#10 Vinicius Junior \(F\)/ });
  expect(btn).toHaveAttribute("aria-pressed", "false");
  fireEvent.click(btn);
  expect(btn).toHaveAttribute("aria-pressed", "true");
});
