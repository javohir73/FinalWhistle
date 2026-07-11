"use client";

/** Wave 3 "scorers" intel section: per-player anytime-try-scorer chances,
 *  split into home/away columns. Adapted from the Task 10 brief's
 *  async-server-component design (`ScorersSection({matchId}) ->
 *  Promise<JSX.Element | null>`, SSR-fetched via a `getNrlScorersServer`)
 *  to this codebase's actual `IntelSectionProps` contract (`{detail,
 *  probHistory}`, rendered synchronously from the "use client"
 *  MatchIntelClient) -- the same drift Task 9 documented and resolved for
 *  LiveSection.tsx, followed here: "use client", default export, matching
 *  IntelSectionProps, deriving matchId/team names from `detail.match.*`,
 *  fetching client-side through `getNrlScorersClient` (the /backend-api
 *  rewrite) rather than a server-only `getServer` fetcher -- so no
 *  `getNrlScorersServer` exists (Task 9 removed its own equivalent as dead
 *  code; see api.ts). No polling: unlike the live score feed, a team list
 *  is static once named, so a single fetch via `useFetch` (no `pollMs`) is
 *  enough. Probabilities only: no odds, no value badges (program-wide
 *  constraint). */
import { getNrlScorersClient } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { pct } from "@/lib/format";
import type { NrlScorer } from "@/lib/types";
import type { IntelSectionProps } from "./sections";

const TOP_N = 6;

export default function ScorersSection({ detail }: IntelSectionProps) {
  const matchId = detail.match.id;
  const home = detail.match.home ?? "Home";
  const away = detail.match.away ?? "Away";

  // Belt-and-braces: coerce through Promise.resolve, not just the fetcher's
  // own promise chain, so an auto-mocked `getNrlScorersClient` (a blanket
  // `jest.mock("@/lib/api")` with no implementation, as page.test.tsx does)
  // degrades to the same quiet "renders nothing" placeholder as a real
  // empty list, instead of useFetch's `fetcher().then(...)` throwing on a
  // non-thenable return -- mirrors LiveSection.tsx's guard.
  const state = useFetch<NrlScorer[]>(
    () => Promise.resolve(getNrlScorersClient(matchId)),
    [matchId],
  );

  // Same quiet messaging as the sibling sections (StatsSection /
  // MatchupSection / LiveSection) when the fetch fails outright.
  if (state.status === "error") {
    return (
      <div className="glass rounded-2xl p-6 text-sm text-muted">
        Try-scorer chances are unavailable right now.
      </div>
    );
  }
  if (state.status !== "success" || !state.data || state.data.length === 0) return null;

  const homeScorers = state.data.filter((s) => s.team === "home");
  const awayScorers = state.data.filter((s) => s.team === "away");

  return (
    <section className="glass rounded-2xl p-6">
      <h2 className="mb-4 font-display text-lg font-bold text-foreground">Try-scorer chances</h2>
      <div className="grid gap-5 sm:grid-cols-2">
        <TeamScorers name={home} players={homeScorers} />
        <TeamScorers name={away} players={awayScorers} />
      </div>
    </section>
  );
}

function TeamScorers({ name, players }: { name: string; players: NrlScorer[] }) {
  const top = [...players].sort((a, b) => b.p_anytime - a.p_anytime).slice(0, TOP_N);
  return (
    <div>
      <div className="text-sm font-bold text-foreground">{name}</div>
      {top.length === 0 ? (
        <p className="mt-2 text-sm text-muted">No team list yet.</p>
      ) : (
        <ul className="mt-2 space-y-1.5">
          {top.map((p) => (
            <li
              key={`${p.jersey}-${p.player}`}
              className="flex items-center justify-between gap-2 text-sm"
            >
              <span className="flex min-w-0 items-center gap-1.5">
                <span className="shrink-0 text-[11px] font-semibold text-muted">{p.position}</span>
                <span className="truncate text-foreground">{p.player}</span>
              </span>
              <span className="shrink-0 font-display font-bold tabular-nums text-lime-deep">
                {pct(p.p_anytime)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
