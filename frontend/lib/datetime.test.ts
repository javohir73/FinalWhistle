import { dayKey, relativeDayLabel } from "@/lib/datetime";

describe("relativeDayLabel", () => {
  // Sun 14 Jun 2026, 21:14 PDT  ==  Mon 15 Jun 2026, 04:14 UTC.
  // This is the real-world case that confused a Pacific-time user: it is still
  // "Sunday" locally, so Monday's fixtures must read as "Tomorrow", not today.
  const now = new Date("2026-06-15T04:14:00Z");
  const PT = "America/Los_Angeles";

  it("labels the user's current local day 'Today'", () => {
    // A match kicking off Sun 14 Jun (PDT), e.g. 18:00 PDT = 01:00Z next day.
    expect(relativeDayLabel("2026-06-15T01:00:00Z", PT, now)).toBe("Today");
  });

  it("labels the next local day 'Tomorrow' even when UTC already rolled over", () => {
    // Mon 15 Jun 09:00 PDT == 16:00Z — UTC says the 15th, but so does PDT here;
    // relative to a Sun-night 'now' it is Tomorrow.
    expect(relativeDayLabel("2026-06-15T16:00:00Z", PT, now)).toBe("Tomorrow");
  });

  it("labels the previous local day 'Yesterday'", () => {
    // Sat 13 Jun 12:00 PDT == 19:00Z.
    expect(relativeDayLabel("2026-06-13T19:00:00Z", PT, now)).toBe("Yesterday");
  });

  it("returns null for days that are neither yesterday, today, nor tomorrow", () => {
    expect(relativeDayLabel("2026-06-20T16:00:00Z", PT, now)).toBeNull();
  });

  it("is evaluated in the given timezone, not UTC", () => {
    // Same instant, different zone: in UTC the kickoff day IS 'now's UTC day...
    expect(dayKey("2026-06-15T04:14:00Z", "UTC")).toBe(dayKey(now.toISOString(), "UTC"));
    // ...so in UTC the Mon-15 16:00Z match is 'Today', but in PDT it is 'Tomorrow'.
    expect(relativeDayLabel("2026-06-15T16:00:00Z", "UTC", now)).toBe("Today");
    expect(relativeDayLabel("2026-06-15T16:00:00Z", PT, now)).toBe("Tomorrow");
  });
});
