"use client";

/** Wave 3 "live" intel section: polls GET /api/nrl/matches/{id}/live every
 *  60s via `useFetch` + `getNrlLiveClient` and hands the resolved payload to
 *  the presentational LiveSectionClient, which pins a sticky banner while
 *  the match is in progress. Team names / match id come straight off the
 *  Wave 1 match detail already threaded through `IntelSectionProps`
 *  (`detail.match.id` / `.home` / `.away`) — the only Wave 1 file this
 *  feature touches is sections.ts (one appended array entry). Renders
 *  nothing before kickoff, and nothing while the first poll is still in
 *  flight (there is no SSR seed available to this client-only render path —
 *  see api.ts's `getNrlLiveServer` doc comment for why). */
import { getNrlLiveClient } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import type { IntelSectionProps } from "./sections";
import { LiveSectionClient } from "./LiveSectionClient";

const POLL_MS = 60_000;

export default function LiveSection({ detail }: IntelSectionProps) {
  const matchId = detail.match.id;
  const home = detail.match.home ?? "Home";
  const away = detail.match.away ?? "Away";
  // Skip polling once the match is already known finished at mount --
  // mirrors the original SSR-`initial`-based guard, adapted to the
  // client-only fetch this section actually has available.
  const alreadyFinished = detail.match.status === "finished";

  // Belt-and-braces: coerce the fetcher's result through Promise.resolve, not
  // just its own promise chain, so an auto-mocked `getNrlLiveClient` (page.test.tsx
  // does a blanket `jest.mock("@/lib/api")` with no implementation for this one)
  // degrades to the same quiet "renders nothing" placeholder as a real 404 or a
  // dropped poll, instead of useFetch's `fetcher().then(...)` throwing on a
  // non-thenable return.
  const state = useFetch(
    () => Promise.resolve(getNrlLiveClient(matchId)),
    [matchId],
    alreadyFinished ? undefined : POLL_MS,
  );

  if (state.status !== "success" || !state.data || state.data.status === "pre") return null;
  return <LiveSectionClient home={home} away={away} live={state.data} />;
}
