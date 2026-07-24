/** Tests the API client calls /api/health (task 1.10). */
import { getHealth, getTeamServer } from "@/lib/api";

describe("api client", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("getHealth calls /api/health and returns the parsed body", async () => {
    const payload = { status: "ok", app: "FinalWhistle", model_version: "x" };
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => payload,
    });
    global.fetch = fetchMock as unknown as typeof fetch;

    const result = await getHealth();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toContain("/api/health");
    expect(result).toEqual(payload);
  });

  it("getHealth throws on non-ok response", async () => {
    global.fetch = jest
      .fn()
      .mockResolvedValue({ ok: false, status: 500 }) as unknown as typeof fetch;

    await expect(getHealth()).rejects.toThrow();
  });

  it("getTeamServer fetches a numeric id", async () => {
    const payload = { team: { id: 37, name: "Argentina" } };
    const fetchMock = jest
      .fn()
      .mockResolvedValue({ ok: true, status: 200, json: async () => payload });
    global.fetch = fetchMock as unknown as typeof fetch;

    const result = await getTeamServer(37);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toContain("/api/teams/37");
    expect(result).toEqual(payload);
  });

  it("getTeamServer short-circuits a non-numeric id to null without fetching", async () => {
    const fetchMock = jest.fn();
    global.fetch = fetchMock as unknown as typeof fetch;

    // A hand-typed /team/Argentina must 404, not 500 off the backend's 422.
    await expect(getTeamServer("Argentina")).resolves.toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
