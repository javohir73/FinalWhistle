/** ShareButton feedback: on desktop (fine pointer) the native share sheet is
 *  skipped, so clicking copies the link to the clipboard and surfaces the
 *  "Link copied!" confirmation. On touch devices the native sheet is preferred
 *  and a successful share also shows the confirmation. */
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ShareButton } from "@/components/ShareButton";

afterEach(() => {
  jest.restoreAllMocks();
});

it("copies the link and shows confirmation on desktop (no native share sheet)", async () => {
  // Desktop: a fine pointer → "(pointer: coarse)" never matches.
  window.matchMedia = jest.fn().mockReturnValue({ matches: false }) as unknown as typeof window.matchMedia;
  const writeText = jest.fn().mockResolvedValue(undefined);
  Object.assign(navigator, { clipboard: { writeText } });

  render(<ShareButton title="X" url="https://example.com/x" />);

  fireEvent.click(screen.getByRole("button"));

  await waitFor(() =>
    expect(screen.getByText("Link copied!")).toBeInTheDocument(),
  );
  expect(writeText).toHaveBeenCalledWith("https://example.com/x");
});

it("prefers the native share sheet on touch devices and confirms a successful share", async () => {
  // Touch: a coarse pointer → "(pointer: coarse)" matches.
  window.matchMedia = jest
    .fn()
    .mockReturnValue({ matches: true }) as unknown as typeof window.matchMedia;
  const share = jest.fn().mockResolvedValue(undefined);
  Object.assign(navigator, { share });

  render(<ShareButton title="X" url="https://example.com/x" />);

  fireEvent.click(screen.getByRole("button"));

  await waitFor(() =>
    expect(screen.getByText("Link copied!")).toBeInTheDocument(),
  );
  expect(share).toHaveBeenCalledWith({ title: "X", url: "https://example.com/x" });
});
