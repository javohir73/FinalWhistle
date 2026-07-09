import { marketLabel, formatDelta } from "@/components/MoversPanel";

describe("movers helpers", () => {
  it("maps market codes to reader copy", () => {
    expect(marketLabel("make_knockout")).toBe("to reach the knockouts");
    expect(marketLabel("win_title")).toBe("to win the Cup");
    expect(marketLabel("qualify_group")).toBe("to qualify from the group");
    expect(marketLabel("win_match")).toBe("to win this round");
    expect(marketLabel("anything_else")).toBe("probability");
  });

  it("formats deltas as signed percentage points, null-safe", () => {
    expect(formatDelta(0.024)).toBe("▲ 2.4");
    expect(formatDelta(-0.016)).toBe("▼ 1.6");
    expect(formatDelta(null)).toBeNull();
  });
});
