import { render, screen, fireEvent } from "@testing-library/react";
import { BracketsClient } from "@/app/brackets/BracketsClient";

it("defaults to the AI bracket view and switches to Official on tab click", () => {
  render(<BracketsClient />);
  // AI is the default active in-page view
  expect(screen.getByRole("tab", { name: "AI bracket" })).toHaveAttribute("aria-selected", "true");

  fireEvent.click(screen.getByRole("tab", { name: "Official" }));
  expect(screen.getByRole("tab", { name: "Official" })).toHaveAttribute("aria-selected", "true");
  // Official tree paints from static topology even with no backend data
  expect(screen.getByLabelText("Official knockout bracket")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Official bracket" })).toBeInTheDocument();
});

it("keeps My picks as a cross-page link", () => {
  render(<BracketsClient />);
  const myPicks = screen.getByRole("tab", { name: "My picks" });
  expect(myPicks.closest("a")).toHaveAttribute("href", "/my-bracket");
});
