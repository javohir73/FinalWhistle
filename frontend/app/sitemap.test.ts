/** Regression test for the Floodlight P1 sitemap bug: the static /matches,
 *  /groups, /brackets entries and the dynamic /match/{id}, /groups/{id},
 *  /team/{id} entries were all now-301'd legacy paths (next.config.mjs), so
 *  Googlebot never saw the live /football/wc26/... URLs in the sitemap at
 *  all. Assert the sitemap emits the live URLs and none of the old ones. */
import sitemap from "./sitemap";

function mockFetchOnce(body: unknown) {
  return Promise.resolve({ ok: true, json: async () => body } as Response);
}

describe("sitemap", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("lists live /football/wc26/... URLs, never the redirecting legacy paths", async () => {
    const fetchMock = jest
      .fn()
      .mockReturnValueOnce(mockFetchOnce([{ match_id: 1 }])) // /api/matches/upcoming
      .mockReturnValueOnce(mockFetchOnce([{ id: 10 }])) // /api/teams
      .mockReturnValueOnce(mockFetchOnce([{ id: 3 }])); // /api/groups
    global.fetch = fetchMock as unknown as typeof fetch;

    const entries = await sitemap();
    const urls = entries.map((e) => e.url);

    expect(urls).toEqual(
      expect.arrayContaining([
        expect.stringContaining("/football/wc26/fixtures"),
        expect.stringContaining("/football/wc26/groups"),
        expect.stringContaining("/football/wc26/bracket"),
        expect.stringContaining("/football/wc26/match/1"),
        expect.stringContaining("/football/wc26/groups/3"),
        expect.stringContaining("/football/wc26/team/10"),
      ]),
    );
    // None of these now-redirecting legacy paths (the exact URLs this bug
    // used to emit) should appear -- checked as exact strings, since the new
    // /football/wc26/... URLs above legitimately end in "/groups" etc. too.
    const site = "https://fifa-wc26-prediction.vercel.app";
    const legacyUrls = [
      `${site}/matches`,
      `${site}/groups`,
      `${site}/brackets`,
      `${site}/match/1`,
      `${site}/groups/3`,
      `${site}/team/10`,
    ];
    for (const legacy of legacyUrls) {
      expect(urls).not.toContain(legacy);
    }
  });
});
