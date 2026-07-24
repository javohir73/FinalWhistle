/** Encode/decode the `picks` query param for /nrl/run-home (design doc: NRL
 *  Round Tips, Slice 3 "the finals-race machine"). Must mirror the backend's
 *  encoding EXACTLY (backend/app/api/nrl_intel.py's `_PICK_RE` and
 *  `_parse_picks`): comma-separated `<match_id><h|a>` tokens, order-
 *  insensitive, no draw option. Pure and framework-free so the roundtrip is
 *  unit-testable without mounting a component. */

export type PickOutcome = "home" | "away";
export type Picks = Record<number, PickOutcome>;

const TOKEN_RE = /^(\d+)([ha])$/;

/** Sorted so the same pick set always produces the same string -- a stable
 *  query/cache key across re-renders, and matches the deterministic seeding
 *  the backend already relies on (season + sorted picks + n_sims). */
export function encodePicks(picks: Picks): string {
  return Object.entries(picks)
    .map(([id, outcome]) => `${id}${outcome === "home" ? "h" : "a"}`)
    .sort()
    .join(",");
}

/** Parse a `?picks=` value into a validated {@link Picks} map. Never throws:
 *  a malformed token, a repeated match id, or a match id outside
 *  `remainingIds` is silently dropped rather than trusted, and `dropped`
 *  comes back true so the caller can show a quiet notice ("some picks in
 *  that link weren't valid") instead of ever crashing on a bad share link. */
export function parsePicksParam(
  raw: string | null | undefined,
  remainingIds: Set<number>,
): { picks: Picks; dropped: boolean } {
  const picks: Picks = {};
  let dropped = false;
  if (!raw) return { picks, dropped };

  for (const rawToken of raw.split(",")) {
    const token = rawToken.trim();
    if (!token) continue;
    const match = TOKEN_RE.exec(token);
    if (!match) {
      dropped = true;
      continue;
    }
    const matchId = Number(match[1]);
    if (matchId in picks || !remainingIds.has(matchId)) {
      dropped = true;
      continue;
    }
    picks[matchId] = match[2] === "h" ? "home" : "away";
  }
  return { picks, dropped };
}
