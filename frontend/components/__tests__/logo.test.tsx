import { render, screen } from "@testing-library/react";
import { BrandMark, Wordmark } from "@/components/Logo";

describe("Logo", () => {
  it("Wordmark renders the FinalWhistle two-tone split", () => {
    render(<Wordmark />);
    expect(screen.getByText("Final")).toBeInTheDocument();
    expect(screen.getByText("Whistle")).toBeInTheDocument();
  });

  it("BrandMark renders a decorative, sizable svg", () => {
    const { container } = render(<BrandMark className="h-7 text-win" />);
    const svg = container.querySelector("svg");
    expect(svg).toBeInTheDocument();
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(svg).toHaveClass("h-7");
  });
});
