import { render } from "@testing-library/react";
import { CompetitionLogo } from "@/components/CompetitionLogo";

describe("CompetitionLogo", () => {
  it("uses a transparent, consistently sized canvas", () => {
    const { container } = render(<CompetitionLogo competition="epl" size={32} />);
    const shell = container.querySelector('[data-competition-logo="epl"]');

    expect(shell).toHaveStyle({ width: "32px", height: "32px" });
    expect(shell).not.toHaveClass("bg-white/95", "ring-1");
    expect(shell?.querySelector("img")).toHaveClass("h-full", "w-full", "object-contain");
  });
});
