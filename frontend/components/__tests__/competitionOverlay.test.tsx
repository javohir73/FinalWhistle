/** CompetitionOverlay — the Floodlight P1 full-screen competition switcher.
 *  The open panel must portal to <body>: SiteNav's header uses backdrop-blur,
 *  and any backdrop-filter makes that header the containing block for fixed
 *  descendants — rendered inline, the panel's "inset-0" resolves against the
 *  60px nav strip instead of the viewport (caught live on the P1 deploy). */
import { fireEvent, render, screen } from "@testing-library/react";
import { CompetitionOverlay } from "@/components/CompetitionOverlay";

let mockPath = "/";
jest.mock("next/navigation", () => ({
  usePathname: () => mockPath,
}));

afterEach(() => {
  mockPath = "/";
  window.localStorage.clear();
});

it("portals the open dialog out of the trigger's ancestor tree (backdrop-filter clipping regression)", () => {
  render(
    <div data-testid="header-shell">
      <CompetitionOverlay />
    </div>
  );
  fireEvent.click(screen.getByRole("button", { name: "WC26" }));
  const dialog = screen.getByRole("dialog", { name: "Choose a competition" });
  expect(screen.getByTestId("header-shell")).not.toContainElement(dialog);
  expect(document.body).toContainElement(dialog);
});

it("separates sports into sections and links every football competition", () => {
  render(<CompetitionOverlay />);
  fireEvent.click(screen.getByRole("button", { name: "WC26" }));
  expect(screen.getByRole("heading", { name: "Football" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "NRL" })).toBeInTheDocument();
  expect(screen.queryByText("Soon")).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Premier League EPL/i })).toHaveAttribute(
    "href",
    "/football/epl",
  );
  expect(screen.getByRole("link", { name: /La Liga LaLiga/i })).toHaveAttribute(
    "href",
    "/football/laliga",
  );
  expect(screen.getByRole("link", { name: /Bundesliga BUN/i })).toHaveAttribute(
    "href",
    "/football/bundesliga",
  );
  expect(screen.getByRole("link", { name: /UEFA Champions League UCL/i })).toHaveAttribute(
    "href",
    "/football/ucl",
  );
});

it("Escape closes the dialog and returns focus to the trigger", () => {
  render(<CompetitionOverlay />);
  const trigger = screen.getByRole("button", { name: "WC26" });
  fireEvent.click(trigger);
  fireEvent.keyDown(window, { key: "Escape" });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(trigger).toHaveFocus();
});
