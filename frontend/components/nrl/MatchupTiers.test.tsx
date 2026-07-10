import { render, screen } from "@testing-library/react";
import { MatchupTiers } from "./MatchupTiers";
import type { NrlStatsProfile } from "@/lib/types";
import { slugify } from "@/lib/nrlSlug";

function profile(name: string, attack: number, defence: number): NrlStatsProfile {
  return {
    team: { id: 1, name, slug: slugify(name) },
    season: 2025,
    attack_rank: attack,
    defence_rank: defence,
    venue_splits: [],
    position_concessions: [],
    disclaimer: "For analytics and entertainment only. Not betting advice.",
  };
}

test("slugify matches the backend rule", () => {
  expect(slugify("Wests Tigers")).toBe("wests-tigers");
  expect(slugify("Knights")).toBe("knights");
});

test("renders attack/defence ranks with tier labels for both clubs", () => {
  render(
    <MatchupTiers
      home={{ name: "Knights", profile: profile("Knights", 2, 10) }}
      away={{ name: "Cowboys", profile: profile("Cowboys", 14, 6) }}
    />,
  );
  expect(screen.getByText("Knights")).toBeInTheDocument();
  expect(screen.getAllByText("Elite").length).toBe(1);      // attack rank 2
  expect(screen.getAllByText("Mid").length).toBe(1);        // defence rank 10
  expect(screen.getAllByText("Struggling").length).toBe(1); // attack rank 14
  expect(screen.getAllByText("Strong").length).toBe(1);     // defence rank 6
  expect(screen.getByText("#2")).toBeInTheDocument();
});

test("missing profile renders em-dashes, not a crash", () => {
  render(
    <MatchupTiers
      home={{ name: "Knights", profile: null }}
      away={{ name: "Cowboys", profile: null }}
    />,
  );
  expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2);
});
