/** Retention page tests — server component (SSR) output. */
import { render, screen } from "@testing-library/react";
import RetentionPage from "./page";
import { getRetentionServer } from "@/lib/api";
import type { RetentionStats } from "@/lib/types";

jest.mock("@/lib/api");
const mockRetention = getRetentionServer as jest.MockedFunction<typeof getRetentionServer>;

const stats: RetentionStats = {
  since: "2026-07-19",
  total_devices: 5,
  dau: [
    { day: "2026-07-19", devices: 3 },
    { day: "2026-07-20", devices: 1 },
  ],
  cohorts: [
    { day: "2026-07-19", cohort_size: 3, d1: 66.7, d7: null, d14: null },
    { day: "2026-07-20", cohort_size: 0, d1: null, d7: null, d14: null },
  ],
};

it("renders the explainer, DAU rows and cohort rows from the fetched stats", async () => {
  mockRetention.mockResolvedValue(stats);
  render(await RetentionPage());

  expect(
    screen.getByText("Anonymous device cohorts measured since the World Cup final — updates daily."),
  ).toBeInTheDocument();
  expect(screen.getByText("5")).toBeInTheDocument(); // total_devices

  // DAU row.
  expect(screen.getAllByText("2026-07-19").length).toBeGreaterThan(0);

  // Cohort row: 66.7% shown, null d7/d14 render as an em dash.
  expect(screen.getByText("66.7%")).toBeInTheDocument();
  expect(screen.getAllByText("—").length).toBeGreaterThan(0);
});

it("shows an error state when the fetch fails", async () => {
  mockRetention.mockRejectedValue(new Error("network down"));
  render(await RetentionPage());

  expect(
    screen.getByText("Retention stats are temporarily unavailable — please check back shortly."),
  ).toBeInTheDocument();
});

it("shows an error state when the API returns null (e.g. a 404 before the migration lands)", async () => {
  mockRetention.mockResolvedValue(null);
  render(await RetentionPage());

  expect(
    screen.getByText("Retention stats are temporarily unavailable — please check back shortly."),
  ).toBeInTheDocument();
});
