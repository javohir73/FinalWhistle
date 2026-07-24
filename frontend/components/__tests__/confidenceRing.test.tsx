/** ConfidenceRing: the conic % dial for the headline prediction. The arc
 *  length prints as the centre %, the tier prints as a WORD, and both carry
 *  through the aria-label — so colour is never the sole signal. */
import { render, screen } from "@testing-library/react";
import { ConfidenceRing } from "@/components/ConfidenceRing";

describe("ConfidenceRing", () => {
  it("prints the %, the tier word, and an aria-label carrying both", () => {
    render(<ConfidenceRing probability={0.62} confidence="High" />);
    expect(screen.getByText("62")).toBeInTheDocument();
    expect(screen.getByText("%")).toBeInTheDocument();
    expect(screen.getByText("HIGH")).toBeInTheDocument();

    const dial = screen.getByRole("img");
    expect(dial).toHaveAttribute("aria-label", expect.stringContaining("62%"));
    expect(dial).toHaveAttribute("aria-label", expect.stringContaining("High confidence"));
  });

  it("prints MEDIUM at the >=12px-bold amber floor", () => {
    render(<ConfidenceRing probability={0.44} confidence="Medium" />);
    const word = screen.getByText("MEDIUM");
    // text-xs (12px) + font-bold clears the 'amber text only >=12px bold' rule.
    expect(word.className).toContain("text-xs");
    expect(word.className).toContain("font-bold");
  });

  it("still renders the % and the ring when confidence is null (unrated)", () => {
    render(<ConfidenceRing probability={0.5} confidence={null} />);
    expect(screen.getByText("50")).toBeInTheDocument();
    const dial = screen.getByRole("img");
    expect(dial).toHaveAttribute("aria-label", expect.stringContaining("unrated"));
    // ring still drawn from probability, no throw.
    expect(dial).toHaveStyle({ borderRadius: "9999px" });
  });
});
