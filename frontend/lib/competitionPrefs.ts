/** Persists the CompetitionOverlay's (components/CompetitionOverlay.tsx, slice
 *  p1-s5) starred/pinned competition across visits. Pure + SSR-safe: every
 *  read/write guards `window` (SSR has none) and wraps localStorage in
 *  try/catch (Safari private mode throws on access, not just on write).
 *  Supersedes SportSwitcher's old fw_sport cookie -- that logic is dropped,
 *  not carried forward, now that the overlay is the one switcher surface. */
import { isCompetitionId, type CompetitionId } from "@/lib/sports";

const KEY = "fw_pinned_comp";

export function readPinnedCompetition(): CompetitionId | null {
  if (typeof window === "undefined") return null;
  try {
    const v = window.localStorage.getItem(KEY);
    return v && isCompetitionId(v) ? v : null;
  } catch {
    return null; // private-mode / disabled storage
  }
}

export function writePinnedCompetition(id: CompetitionId): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(KEY, id);
  } catch {
    /* ignore */
  }
}

export function clearPinnedCompetition(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}
