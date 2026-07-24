/** Picks encode/decode must mirror backend/app/api/nrl_intel.py's `_PICK_RE`/
 *  `_parse_picks` exactly -- this is the contract the frontend can't drift
 *  from without every share link silently breaking. */
import { encodePicks, parsePicksParam } from "./nrlRunHomePicks";

describe("encodePicks", () => {
  it("encodes a picks map into sorted <match_id><h|a> tokens", () => {
    expect(encodePicks({ 456: "away", 123: "home" })).toBe("123h,456a");
  });

  it("returns an empty string for no picks", () => {
    expect(encodePicks({})).toBe("");
  });
});

describe("parsePicksParam", () => {
  const remaining = new Set([123, 456, 789]);

  it("roundtrips through encodePicks", () => {
    const picks = { 123: "home", 456: "away" } as const;
    const { picks: parsed, dropped } = parsePicksParam(encodePicks(picks), remaining);
    expect(parsed).toEqual(picks);
    expect(dropped).toBe(false);
  });

  it("returns empty, non-dropped state for null/empty input", () => {
    expect(parsePicksParam(null, remaining)).toEqual({ picks: {}, dropped: false });
    expect(parsePicksParam("", remaining)).toEqual({ picks: {}, dropped: false });
  });

  it("drops a malformed token but keeps the valid ones", () => {
    const { picks, dropped } = parsePicksParam("123h,not-a-token,456a", remaining);
    expect(picks).toEqual({ 123: "home", 456: "away" });
    expect(dropped).toBe(true);
  });

  it("drops a token naming a match outside the remaining set", () => {
    const { picks, dropped } = parsePicksParam("123h,999a", remaining);
    expect(picks).toEqual({ 123: "home" });
    expect(dropped).toBe(true);
  });

  it("keeps only the first occurrence of a duplicated match id", () => {
    const { picks, dropped } = parsePicksParam("123h,123a", remaining);
    expect(picks).toEqual({ 123: "home" });
    expect(dropped).toBe(true);
  });

  it("rejects a draw-shaped token (no draw option in this encoding)", () => {
    const { picks, dropped } = parsePicksParam("123d", remaining);
    expect(picks).toEqual({});
    expect(dropped).toBe(true);
  });
});
