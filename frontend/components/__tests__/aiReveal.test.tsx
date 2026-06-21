/** AICalculationReveal: the precomputed forecast reveal auto-completes, is
 *  skippable at any time (without double-firing onComplete), and only plays the
 *  full version once per device. */
import { render, screen, fireEvent, act } from "@testing-library/react";
import { AICalculationReveal } from "@/components/AICalculationReveal";

const SEEN_KEY = "finalwhistle:reveal-seen:v1";

beforeEach(() => localStorage.clear());
afterEach(() => jest.useRealTimers());

it("auto-completes after the reveal and remembers it for next time", () => {
  jest.useFakeTimers();
  const onComplete = jest.fn();
  render(<AICalculationReveal team="Brazil" onComplete={onComplete} />);

  act(() => {
    jest.advanceTimersByTime(3600); // past the full ~3.4s first-run duration
  });

  expect(onComplete).toHaveBeenCalledTimes(1);
  expect(localStorage.getItem(SEEN_KEY)).toBe("1");
});

it("skips immediately when Skip is tapped, and never double-fires", () => {
  jest.useFakeTimers();
  const onComplete = jest.fn();
  render(<AICalculationReveal team="Brazil" onComplete={onComplete} />);

  fireEvent.click(screen.getByRole("button", { name: /skip/i }));
  expect(onComplete).toHaveBeenCalledTimes(1);

  // The pending auto-complete timeout must not fire a second completion.
  act(() => {
    jest.advanceTimersByTime(4000);
  });
  expect(onComplete).toHaveBeenCalledTimes(1);
});

it("uses the quick path once the reveal has been seen on this device", () => {
  localStorage.setItem(SEEN_KEY, "1");
  jest.useFakeTimers();
  const onComplete = jest.fn();
  render(<AICalculationReveal team="Brazil" onComplete={onComplete} />);

  // Short 900ms path: complete well before the full duration would elapse.
  act(() => {
    jest.advanceTimersByTime(1100);
  });
  expect(onComplete).toHaveBeenCalledTimes(1);
});
