/** TeamSearch: a home-dashboard combobox to jump to any nation's profile.
 *  Typing filters the dropdown; selecting (click or Enter on the highlighted
 *  row) navigates to /team/[id]. Keyboard- and screen-reader-accessible. */
import { render, screen, fireEvent } from "@testing-library/react";
import { TeamSearch } from "@/components/TeamSearch";
import type { Team } from "@/lib/types";

const push = jest.fn();
jest.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

const team = (id: number, name: string): Team => ({
  id,
  name,
  country_code: null,
  confederation: null,
  fifa_rank: null,
  elo_rating: null,
  is_host: false,
});

const teams: Team[] = [
  team(1, "Argentina"),
  team(2, "Brazil"),
  team(3, "Spain"),
];

afterEach(() => push.mockReset());

const type = (value: string) =>
  fireEvent.change(screen.getByRole("combobox"), { target: { value } });

it("shows no dropdown options until the user types", () => {
  render(<TeamSearch teams={teams} />);
  expect(screen.queryByRole("option")).not.toBeInTheDocument();
});

it("filters the dropdown to matching teams as you type", () => {
  render(<TeamSearch teams={teams} />);
  type("bra");
  expect(screen.getByRole("option", { name: /Brazil/ })).toBeInTheDocument();
  expect(screen.queryByRole("option", { name: /Argentina/ })).not.toBeInTheDocument();
});

it("navigates to the team profile when a result is clicked", () => {
  render(<TeamSearch teams={teams} />);
  type("spa");
  fireEvent.click(screen.getByRole("option", { name: /Spain/ }));
  expect(push).toHaveBeenCalledWith("/team/3");
});

it("highlights with ArrowDown and navigates the highlighted team on Enter", () => {
  render(<TeamSearch teams={teams} />);
  const input = screen.getByRole("combobox");
  type("a"); // matches Argentina (prefix) then Spain (substring): Argentina first
  fireEvent.keyDown(input, { key: "ArrowDown" });
  fireEvent.keyDown(input, { key: "Enter" });
  expect(push).toHaveBeenCalledWith("/team/1");
});

it("shows a no-match message when nothing matches", () => {
  render(<TeamSearch teams={teams} />);
  type("zzz");
  expect(screen.queryByRole("option")).not.toBeInTheDocument();
  expect(screen.getByText(/No team matches/i)).toBeInTheDocument();
});

it("closes the dropdown on Escape", () => {
  render(<TeamSearch teams={teams} />);
  const input = screen.getByRole("combobox");
  type("bra");
  expect(screen.getByRole("option", { name: /Brazil/ })).toBeInTheDocument();
  fireEvent.keyDown(input, { key: "Escape" });
  expect(screen.queryByRole("option")).not.toBeInTheDocument();
});
