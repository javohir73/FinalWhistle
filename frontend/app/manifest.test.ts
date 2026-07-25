/** Floodlight P6 guard for the PWA manifest. The polish pass verified the
 *  manifest by hand — canvas-token chrome colours, standalone/portrait, and an
 *  icons array that must never reference an asset missing from public/. These
 *  assertions lock that in so a future icon rename can't silently ship a
 *  dangling manifest reference (Android/Chrome drop the whole icon set). */
import { existsSync } from "fs";
import { join } from "path";
import manifest from "./manifest";

jest.mock("@/lib/tournament", () => ({
  getTournament: async () => ({
    id: 0,
    name: "World Cup 2026",
    year: 2026,
    format: "knockout",
    has_brackets: true,
  }),
}));

const PUBLIC_DIR = join(__dirname, "..", "public");

describe("PWA manifest", () => {
  it("uses the prototype's Floodlight green-black canvas for both chrome colours", async () => {
    const m = await manifest();
    // Matches design/Floodlight Prototype.dc.html and --background exactly.
    expect(m.background_color).toBe("#0a1410");
    expect(m.theme_color).toBe("#0a1410");
  });

  it("declares a standalone, portrait, root-scoped installable app", async () => {
    const m = await manifest();
    expect(m.id).toBe("/");
    expect(m.start_url).toBe("/");
    expect(m.scope).toBe("/");
    expect(m.display).toBe("standalone");
    expect(m.orientation).toBe("portrait");
    expect(m.lang).toBe("en");
  });

  it("references only icons that exist on disk in public/", async () => {
    const m = await manifest();
    expect(m.icons?.length).toBeGreaterThan(0);
    for (const icon of m.icons ?? []) {
      expect(existsSync(join(PUBLIC_DIR, icon.src))).toBe(true);
    }
  });

  it("ships distinct any + maskable icon purposes", async () => {
    const m = await manifest();
    const purposes = (m.icons ?? []).map((i) => i.purpose);
    expect(purposes).toContain("any");
    expect(purposes).toContain("maskable");
  });
});
