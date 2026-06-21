/** useFetch.retry(): a failed fetch surfaces an error state carrying a retry()
 *  that re-runs the fetcher and recovers to success — the recovery path for the
 *  free-tier backend's cold starts. */
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { useFetch } from "@/lib/useFetch";

function Probe({ fetcher }: { fetcher: () => Promise<string> }) {
  const state = useFetch(fetcher, []);
  return (
    <div>
      <span data-testid="status">{state.status}</span>
      {state.status === "success" && <span data-testid="data">{state.data}</span>}
      {state.status === "error" && (
        <button type="button" onClick={state.retry}>
          retry
        </button>
      )}
    </div>
  );
}

it("recovers from a failed fetch when retry() succeeds", async () => {
  const fetcher = jest
    .fn()
    .mockImplementationOnce(() => Promise.reject(new Error("cold start")))
    .mockImplementationOnce(() => Promise.resolve("ok"));

  render(<Probe fetcher={fetcher} />);

  // First attempt fails → error state with a retry control.
  await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("error"));
  expect(fetcher).toHaveBeenCalledTimes(1);

  // Retry re-runs the fetcher and recovers to success.
  fireEvent.click(screen.getByText("retry"));
  await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("success"));
  expect(screen.getByTestId("data")).toHaveTextContent("ok");
  expect(fetcher).toHaveBeenCalledTimes(2);
});
