/** GroupCard: whole-card navigation vs. team-link navigation. */
import { render, screen, fireEvent } from "@testing-library/react";
import { GroupCard } from "@/components/GroupCard";
import type { Group } from "@/lib/types";

const push = jest.fn();
jest.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

const group: Group = {
  id: 1,
  name: "Group A",
  standings: [
    { team_id: 10, team: "Mexico", projected_points: 7, projected_goals_for: 5, projected_goal_diff: 4, qualification_prob: 0.89 },
    { team_id: 20, team: "South Korea", projected_points: 5, projected_goals_for: 4, projected_goal_diff: 1, qualification_prob: 0.6 },
    { team_id: 30, team: "Czechia", projected_points: 4, projected_goals_for: 3, projected_goal_diff: -1, qualification_prob: 0.39 },
    { team_id: 40, team: "South Africa", projected_points: 2, projected_goals_for: 2, projected_goal_diff: -4, qualification_prob: 0.12 },
  ],
};

afterEach(() => push.mockReset());

it("navigates to the group when the card is clicked", () => {
  render(<GroupCard group={group} />);
  fireEvent.click(screen.getByRole("link", { name: /Group A/i }));
  expect(push).toHaveBeenCalledWith("/groups/1");
});

it("opens the group on Enter (keyboard support)", () => {
  render(<GroupCard group={group} />);
  fireEvent.keyDown(screen.getByRole("link", { name: /Group A/i }), { key: "Enter" });
  expect(push).toHaveBeenCalledWith("/groups/1");
});

it("clicking a team name goes to the team, not the group", () => {
  render(<GroupCard group={group} />);
  const teamLink = screen.getByRole("link", { name: /Mexico/i });
  expect(teamLink).toHaveAttribute("href", "/team/10");
  // stopPropagation must prevent the card's group navigation from firing.
  fireEvent.click(teamLink);
  expect(push).not.toHaveBeenCalled();
});

it("shows the 'View matches' affordance", () => {
  render(<GroupCard group={group} />);
  expect(screen.getByText(/View matches/i)).toBeInTheDocument();
});
