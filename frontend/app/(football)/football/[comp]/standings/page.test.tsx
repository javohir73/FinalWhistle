/** The /football/{comp}/standings wrapper serves every wired league while
 *  keeping WC26 on its namespaced groups-backed standings URL. */
import CompStandingsPage, { generateMetadata } from "./page";

it("renders a competition-scoped standings surface for EPL", async () => {
  const element = await CompStandingsPage({
    params: Promise.resolve({ comp: "epl" }),
  });
  expect(element.props.comp).toBe("epl");
});

it("renders the Champions League league-phase standings surface", async () => {
  const element = await CompStandingsPage({
    params: Promise.resolve({ comp: "ucl" }),
  });
  expect(element.props.comp).toBe("ucl");
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
