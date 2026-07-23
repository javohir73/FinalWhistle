/** ActivityPing: fires the once-a-day device ping on mount and renders
 *  nothing (a side-effect-only component, like ServiceWorker/SentryInit). */
import { render } from "@testing-library/react";
import { ActivityPing } from "@/components/ActivityPing";
import * as session from "@/lib/session";

jest.mock("@/lib/session");
const mockPing = session.pingDailyActivity as jest.MockedFunction<typeof session.pingDailyActivity>;

afterEach(() => jest.resetAllMocks());

it("fires pingDailyActivity exactly once on mount", () => {
  mockPing.mockResolvedValue(undefined);
  const { container } = render(<ActivityPing />);

  expect(mockPing).toHaveBeenCalledTimes(1);
  expect(container).toBeEmptyDOMElement(); // renders nothing
});

it("never throws even if the ping rejects", () => {
  mockPing.mockRejectedValue(new Error("network down"));
  expect(() => render(<ActivityPing />)).not.toThrow();
});
