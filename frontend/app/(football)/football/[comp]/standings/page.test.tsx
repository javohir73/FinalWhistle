/** The /football/{comp}/standings wrapper is dormant in P2: it renders only for
 *  wired *league-format* football competitions, of which there are none yet
 *  (epl/laliga/bundesliga stay enabled:false). So it must notFound() for a
 *  disabled comp, and — since WC26's standings live at /groups — for WC26 too,
 *  keeping exactly one canonical URL. notFound() throws, so a guarded render
 *  rejects. */
import CompStandingsPage, { generateMetadata } from "./page";

it("notFound()s for a disabled league comp (epl is not enabled until its data ships)", async () => {
  await expect(
    CompStandingsPage({ params: Promise.resolve({ comp: "epl" }) }),
  ).rejects.toThrow();
});

it("notFound()s for WC26 — its standings live at /groups, not here", async () => {
  await expect(
    CompStandingsPage({ params: Promise.resolve({ comp: "wc26" }) }),
  ).rejects.toThrow();
});

it("notFound()s for an unknown comp", async () => {
  await expect(
    CompStandingsPage({ params: Promise.resolve({ comp: "not-a-comp" }) }),
  ).rejects.toThrow();
});

it("still resolves a title for a disabled comp without throwing", async () => {
  const meta = await generateMetadata({ params: Promise.resolve({ comp: "not-a-comp" }) });
  expect(meta.title).toBe("Football standings");
});
