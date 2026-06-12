/** Engagement signals that gate the install-app prompt (never shown on first
 *  load — only once the user has actually played with the product).
 *
 *  Threshold (PRD FR 22), any of:
 *    - made at least one pick (bracket or per-match),
 *    - visited My Bracket twice,
 *    - opened the menu/settings.
 *
 *  Counters live in localStorage; a custom event keeps any mounted listeners
 *  (the prompt) in sync within the tab. */

const KEY = "finalwhistle:engagement:v1";
export const ENGAGEMENT_EVENT = "finalwhistle:engagement-changed";

export type EngagementSignal = "pick" | "my-bracket-visit" | "menu-open";

interface Engagement {
  picks: number;
  myBracketVisits: number;
  menuOpens: number;
}

// Always a fresh object — callers (recordEngagement) mutate the result.
const empty = (): Engagement => ({ picks: 0, myBracketVisits: 0, menuOpens: 0 });

export function loadEngagement(): Engagement {
  if (typeof window === "undefined") return empty();
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return empty();
    const parsed = JSON.parse(raw) as Partial<Engagement>;
    return {
      picks: Number(parsed.picks) || 0,
      myBracketVisits: Number(parsed.myBracketVisits) || 0,
      menuOpens: Number(parsed.menuOpens) || 0,
    };
  } catch {
    return empty();
  }
}

export function recordEngagement(signal: EngagementSignal): void {
  if (typeof window === "undefined") return;
  try {
    const e = loadEngagement();
    if (signal === "pick") e.picks += 1;
    else if (signal === "my-bracket-visit") e.myBracketVisits += 1;
    else e.menuOpens += 1;
    window.localStorage.setItem(KEY, JSON.stringify(e));
    window.dispatchEvent(new Event(ENGAGEMENT_EVENT));
  } catch {
    /* storage unavailable (private mode / quota) — non-fatal */
  }
}

/** Has the user crossed the "meaningfully engaged" line? */
export function isEngaged(): boolean {
  const e = loadEngagement();
  return e.picks >= 1 || e.myBracketVisits >= 2 || e.menuOpens >= 1;
}
