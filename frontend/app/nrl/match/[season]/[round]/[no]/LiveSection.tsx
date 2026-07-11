"use client";

/** Wave 3 "live" intel section: polls GET /api/nrl/matches/{id}/live every
 *  60s via `useFetch` + `getNrlLiveClient` and hands the resolved payload to
 *  the presentational LiveSectionClient (in-flow card + fixed pinned strip
 *  while in progress). Team names / match id come straight off the Wave 1
 *  match detail already threaded through `IntelSectionProps`
 *  (`detail.match.id` / `.home` / `.away`) — the only Wave 1 file this
 *  feature touches is sections.ts (one appended array entry). Renders
 *  nothing before kickoff. */
import { getNrlLiveClient } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import type { NrlLive } from "@/lib/types";
import type { IntelSectionProps } from "./sections";
import { LiveSectionClient } from "./LiveSectionClient";

const POLL_MS = 60_000;

export default function LiveSection({ detail }: IntelSectionProps) {
  const m = detail.match;
  const matchId = m.id;
  const home = m.home ?? "Home";
  const away = m.away ?? "Away";
  // Skip polling once the match is already known finished at mount.
  const alreadyFinished = m.status === "finished";

  // First-paint seed: a finished match's live payload is fully determined by
  // data already on the page, mirroring the backend's own no-state fallback
  // verbatim (nrl_live.py: minute 80, live_home_prob 1/0 by winner, draws 0)
  // -- so the Final card is in the first paint with no fetch round-trip. The
  // fetch still runs once and silently replaces this with the persisted
  // closing prob + events. A live match is deliberately NOT seeded: its
  // live_home_prob is a model output we won't fabricate client-side, so it
  // paints on the first poll instead.
  const seed: NrlLive | undefined =
    alreadyFinished && m.score_home != null && m.score_away != null
      ? {
          status: "final",
          minute: 80,
          score_home: m.score_home,
          score_away: m.score_away,
          live_home_prob: m.score_home > m.score_away ? 1 : 0,
          events: [],
        }
      : undefined;

  // Belt-and-braces: coerce the fetcher's result through Promise.resolve, not
  // just its own promise chain, so an auto-mocked `getNrlLiveClient` (page.test.tsx
  // does a blanket `jest.mock("@/lib/api")` with no implementation for this one)
  // degrades to the same quiet "renders nothing" placeholder as a real "pre"
  // payload, instead of useFetch's `fetcher().then(...)` throwing on a
  // non-thenable return.
  const state = useFetch<NrlLive>(
    () => Promise.resolve(getNrlLiveClient(matchId)),
    [matchId],
    alreadyFinished ? undefined : POLL_MS,
    seed,
  );

  // Same quiet messaging as the sibling sections (StatsSection /
  // MatchupSection) when the fetch fails outright; a later successful poll
  // replaces this in place.
  if (state.status === "error") {
    return (
      <div className="glass rounded-2xl p-6 text-sm text-muted">
        Live updates are unavailable right now.
      </div>
    );
  }
  if (state.status !== "success" || !state.data || state.data.status === "pre") return null;
  return <LiveSectionClient home={home} away={away} live={state.data} />;
}
