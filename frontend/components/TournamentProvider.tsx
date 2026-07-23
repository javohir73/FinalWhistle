"use client";

import { createContext, useContext } from "react";
import type { ActiveTournament } from "@/lib/types";
import { WC26_FALLBACK } from "@/lib/tournament";

/** Defaults to the WC26 fallback (not null) — a component rendered outside
 *  the provider (e.g. in a test) still degrades to today's behavior instead
 *  of throwing, matching every other tournament-context fallback in this PR. */
const TournamentContext = createContext<ActiveTournament>(WC26_FALLBACK);

/** Makes the server-resolved active tournament (lib/tournament.ts) available
 *  to client components — nav gating (C6, SiteNav/BottomNav) needs
 *  `has_brackets` before those components can decide what to render. */
export function TournamentProvider({
  tournament,
  children,
}: {
  tournament: ActiveTournament;
  children: React.ReactNode;
}) {
  return (
    <TournamentContext.Provider value={tournament}>{children}</TournamentContext.Provider>
  );
}

export function useTournament(): ActiveTournament {
  return useContext(TournamentContext);
}
