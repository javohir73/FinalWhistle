/** Tests the homepage renders backend connectivity status (task 1.10). */
import { render, screen, waitFor } from "@testing-library/react";
import HomePage from "./page";
import { getHealth } from "@/lib/api";

jest.mock("@/lib/api");
const mockedGetHealth = getHealth as jest.MockedFunction<typeof getHealth>;

describe("HomePage", () => {
  afterEach(() => jest.resetAllMocks());

  it("shows connected status when the backend responds", async () => {
    mockedGetHealth.mockResolvedValue({
      status: "ok",
      app: "PitchProphet",
      model_version: "poisson-elo-v0.1",
    });

    render(<HomePage />);

    await waitFor(() =>
      expect(screen.getByText(/Connected/i)).toBeInTheDocument(),
    );
    expect(
      screen.getByRole("heading", { name: "PitchProphet" }),
    ).toBeInTheDocument();
  });

  it("shows an error when the backend is unreachable", async () => {
    mockedGetHealth.mockRejectedValue(new Error("boom"));

    render(<HomePage />);

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/Cannot reach backend/i),
    );
  });
});
