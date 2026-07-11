import { sections } from "./sections";

it("ships overview, form, model, stats, matchup, live and scorers in that order", () => {
  expect(sections.map((s) => s.id)).toEqual([
    "overview", "form", "model", "stats", "matchup", "live", "scorers",
  ]);
});

it("every section has a label and a render component", () => {
  for (const s of sections) {
    expect(typeof s.label).toBe("string");
    expect(s.label.length).toBeGreaterThan(0);
    expect(typeof s.render).toBe("function");
  }
});
