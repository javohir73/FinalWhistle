import { render } from "@testing-library/react";
import { TeamBadge } from "@/components/TeamBadge";

describe("TeamBadge", () => {
  it("keeps national teams on their self-hosted flags", () => {
    const { container } = render(<TeamBadge team="Brazil" size={32} />);
    expect(container.querySelector("img")).toHaveAttribute("src", "/flags/br.png");
    expect(container.querySelector("[data-club-logo]")).toBeNull();
  });

  it("uses a self-hosted crest for a known domestic club", () => {
    const { container } = render(<TeamBadge team="Arsenal" size={32} />);
    const shell = container.querySelector('[data-club-logo="Arsenal"]');
    expect(shell).not.toHaveClass("bg-white/95", "ring-1");
    expect(shell?.querySelector("img")).toHaveAttribute("src", "/clubs/epl/arsenal.png");
    expect(shell?.querySelector("img")).toHaveClass("h-full", "w-full", "object-contain");
  });

  it("resolves common short club names to the same local crest", () => {
    const { container } = render(<TeamBadge team="Man City" size={32} />);
    expect(container.querySelector('[data-club-logo="Man City"] img')).toHaveAttribute(
      "src",
      "/clubs/epl/manchester-city.png",
    );
  });
});
