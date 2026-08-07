/** The header theme control. */
import { render, screen, fireEvent } from "@testing-library/react";
import { ThemeToggle } from "@/components/ThemeToggle";
import { LIGHT_CLASS, THEME_KEY } from "@/lib/theme";

afterEach(() => {
  window.localStorage.clear();
  document.documentElement.className = "";
});

it("offers the theme you are NOT in, and says so", () => {
  render(<ThemeToggle />);
  expect(screen.getByRole("button", { name: "Switch to light theme" })).toBeInTheDocument();
});

it("switches the document, persists the choice, and re-labels itself", () => {
  render(<ThemeToggle />);
  fireEvent.click(screen.getByRole("button", { name: "Switch to light theme" }));

  expect(document.documentElement.classList.contains(LIGHT_CLASS)).toBe(true);
  expect(window.localStorage.getItem(THEME_KEY)).toBe("light");
  expect(screen.getByRole("button", { name: "Switch to dark theme" })).toBeInTheDocument();
});

it("switches back", () => {
  render(<ThemeToggle />);
  fireEvent.click(screen.getByRole("button", { name: "Switch to light theme" }));
  fireEvent.click(screen.getByRole("button", { name: "Switch to dark theme" }));

  expect(document.documentElement.classList.contains(LIGHT_CLASS)).toBe(false);
  expect(window.localStorage.getItem(THEME_KEY)).toBe("dark");
});

it("reflects an already-stored choice on mount", () => {
  window.localStorage.setItem(THEME_KEY, "light");
  render(<ThemeToggle />);
  // Mounted while light -> it must offer dark, not re-offer light.
  expect(screen.getByRole("button", { name: "Switch to dark theme" })).toBeInTheDocument();
});

it("carries an accessible name without relying on the icon", () => {
  render(<ThemeToggle />);
  const btn = screen.getByRole("button");
  expect(btn).toHaveAttribute("aria-label");
  expect(btn.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
});
