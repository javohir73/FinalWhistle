/** Shared Skeleton primitives: the shimmer block is decorative (`.skeleton` +
 *  aria-hidden) while the announcing role="status" lives on the SkeletonScreen
 *  wrapper. SkeletonRows reserves one row per requested slot. */
import { render, screen } from "@testing-library/react";
import {
  Skeleton,
  SkeletonScreen,
  SkeletonRows,
} from "@/components/Skeleton";

describe("Skeleton", () => {
  it("renders the shimmer .skeleton class and merges caller layout classes", () => {
    const { container } = render(<Skeleton className="h-4 w-20 rounded" />);
    const block = container.firstElementChild!;
    expect(block).toHaveClass("skeleton", "h-4", "w-20", "rounded");
  });

  it("is aria-hidden so the shimmer block is not announced", () => {
    const { container } = render(<Skeleton />);
    expect(container.firstElementChild).toHaveAttribute("aria-hidden", "true");
  });
});

describe("SkeletonScreen", () => {
  it("exposes a single role=status with the given aria-label", () => {
    render(
      <SkeletonScreen label="Loading fixtures…">
        <Skeleton />
      </SkeletonScreen>,
    );
    const status = screen.getByRole("status");
    expect(status).toHaveAttribute("aria-label", "Loading fixtures…");
  });
});

describe("SkeletonRows", () => {
  it("renders the requested row count (plus a header bar)", () => {
    const { container } = render(<SkeletonRows rows={5} />);
    // Rows carry `h-9`; the header bar does not — so counting h-9 blocks is an
    // exact row count independent of the header.
    expect(container.querySelectorAll(".skeleton.h-9")).toHaveLength(5);
  });
});
