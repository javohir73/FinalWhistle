import { render, screen, fireEvent } from "@testing-library/react";
import { BracketsClient } from "@/app/brackets/BracketsClient";

it("defaults to the Official bracket view and switches to AI on tab click", () => {
  render(<BracketsClient />);
  // Official is the default active in-page view; the tree paints from static
  // topology even with no backend data.
  expect(screen.getByRole("tab", { name: "Official" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByLabelText("Official knockout bracket")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Official bracket" })).toBeInTheDocument();

  fireEvent.click(screen.getByRole("tab", { name: "AI bracket" }));
  expect(screen.getByRole("tab", { name: "AI bracket" })).toHaveAttribute("aria-selected", "true");
});

it("shows only Official and AI bracket tabs (no My picks)", () => {
  render(<BracketsClient />);
  expect(screen.getByRole("tab", { name: "Official" })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "AI bracket" })).toBeInTheDocument();
  expect(screen.queryByRole("tab", { name: "My picks" })).toBeNull();
});
