/** /groups route skeleton: one status announcement plus a glass card per group
 *  in the two-column grid, each reserving four table rows. */
import { render, screen } from "@testing-library/react";
import GroupsLoading from "./loading";

it("announces a single 'Loading groups…' status", () => {
  render(<GroupsLoading />);
  expect(screen.getByRole("status")).toHaveAttribute("aria-label", "Loading groups…");
});

it("reserves four rows per group card (8 cards)", () => {
  const { container } = render(<GroupsLoading />);
  // SkeletonRows rows are the `h-9 rounded-lg` blocks (the header bar is `rounded`,
  // not `rounded-lg`); 8 group cards × 4 rows = 32 row blocks.
  expect(container.querySelectorAll(".skeleton.h-9.rounded-lg")).toHaveLength(32);
});
