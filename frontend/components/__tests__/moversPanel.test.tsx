import { render, screen, waitFor } from "@testing-library/react";
import { MoversPanel } from "@/components/MoversPanel";
import { getMovers } from "@/lib/api";
import type { Mover } from "@/lib/types";

jest.mock("@/lib/api");
const mockGetMovers = getMovers as jest.MockedFunction<typeof getMovers>;

const movers: Mover[] = [
  {
    entity_id: 16, name: "Warriors", market: "win_match",
    prob: 0.63, delta: 0.02, series: [0.6, 0.63], match_url: "/nrl/match/2026/19/3",
  },
];

afterEach(() => jest.resetAllMocks());

it("links an NRL win_match row to its match detail page", async () => {
  mockGetMovers.mockResolvedValue({
    sport: "nrl", as_of: "2026-07-10", movers,
    disclaimer: "For analytics and entertainment only. Not betting advice.",
  });
  render(<MoversPanel sport="nrl" />);

  await waitFor(() => expect(screen.getByText("Warriors")).toBeInTheDocument());
  expect(screen.getByRole("link", { name: /Warriors/ })).toHaveAttribute(
    "href", "/nrl/match/2026/19/3",
  );
});

it("renders a plain row when match_url is null", async () => {
  mockGetMovers.mockResolvedValue({
    sport: "nrl", as_of: "2026-07-10",
    movers: [{ ...movers[0], match_url: null }],
    disclaimer: "For analytics and entertainment only. Not betting advice.",
  });
  render(<MoversPanel sport="nrl" />);

  await waitFor(() => expect(screen.getByText("Warriors")).toBeInTheDocument());
  expect(screen.queryByRole("link", { name: /Warriors/ })).not.toBeInTheDocument();
});
