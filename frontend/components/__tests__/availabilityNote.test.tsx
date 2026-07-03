import { render, screen } from "@testing-library/react";
import { AvailabilityNote } from "@/components/AvailabilityNote";
import type { Availability } from "@/lib/types";

const availability: Availability = {
  has_lineup: true,
  per_team: [
    { side: "home", attack_delta_pct: -0.08, note: "France: usual XI missing Mbappe → attack -8%.",
      players_out: [{ name: "Mbappe", weight: 0.58 }] },
    { side: "away", attack_delta_pct: 0.0, note: "Senegal: announced XI at full attacking strength.",
      players_out: [] },
  ],
};

test("renders per-team notes and the not-in-the-number caveat", () => {
  render(<AvailabilityNote availability={availability} />);
  expect(screen.getByText(/France: usual XI missing Mbappe/)).toBeInTheDocument();
  expect(screen.getByText(/Senegal: announced XI at full attacking strength/)).toBeInTheDocument();
  expect(screen.getByText(/not reflected in the number above/i)).toBeInTheDocument();
});

test("renders nothing when there is no lineup", () => {
  const { container } = render(<AvailabilityNote availability={null} />);
  expect(container).toBeEmptyDOMElement();
});
