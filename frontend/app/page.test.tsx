import { metadata } from "./page";

it("describes the World Cup root instead of inheriting the active league title", () => {
  expect(metadata.title).toBe("World Cup 2026 predictions — FinalWhistle");
  expect(metadata.description).toContain("World Cup 2026");
});
