/** The calibration curve on /methodology rendered empty for the same reason
 *  the "Most important factors" chart did: its ResponsiveContainer was given no
 *  height, so it defaulted to "100%" and measured a 0-height parent — recharts
 *  then warned and drew nothing. The component now passes an explicit pixel
 *  height, so the chart always has a real box. recharts' SVG layout is
 *  unreliable under jsdom (it depends on text/element measurement jsdom can't
 *  do), so we stub recharts to a thin pass-through and assert on the non-zero
 *  height the component derives — the wrapper's inline height and the matching
 *  height handed to the ResponsiveContainer, which is the actual fix. */
import { render, screen } from "@testing-library/react";

// Pass-through recharts: ResponsiveContainer surfaces the width/height it was
// given, and LineChart surfaces how many data points it received, so the
// component's wiring is visible to the DOM without relying on recharts' SVG.
jest.mock("recharts", () => {
  const React = require("react");
  return {
    __esModule: true,
    ResponsiveContainer: ({ width, height, children }: any) =>
      React.createElement(
        "div",
        { "data-testid": "rc-container", "data-width": String(width), "data-height": String(height) },
        children,
      ),
    LineChart: ({ data, children }: any) =>
      React.createElement(
        "div",
        { "data-testid": "rc-linechart", "data-points": String(data.length) },
        children,
      ),
    Line: () => null,
    CartesianGrid: () => null,
    Tooltip: () => null,
    XAxis: () => null,
    YAxis: () => null,
  };
});

// eslint-disable-next-line import/first
import { CalibrationChart } from "@/components/CalibrationChart";

const BINS = [
  { mean_predicted: 0.1, empirical_freq: 0.08, count: 40 },
  { mean_predicted: 0.5, empirical_freq: 0.52, count: 120 },
  { mean_predicted: 0.9, empirical_freq: 0.93, count: 35 },
];

describe("CalibrationChart", () => {
  it("renders the chart inside a box with an explicit, non-zero height", () => {
    const { container } = render(<CalibrationChart bins={BINS} />);

    // The chart is wired up with every bin as a data point.
    expect(screen.getByTestId("rc-linechart").getAttribute("data-points")).toBe(
      String(BINS.length),
    );

    // The fix: the wrapper carries an explicit, non-zero inline height so
    // recharts has a real box to draw into (height 0 was the empty section).
    const wrapper = container.firstElementChild as HTMLElement;
    expect(parseInt(wrapper.style.height, 10)).toBeGreaterThan(0);
    // And that same height is handed to the container instead of defaulting to
    // "100%" of a measured-0 parent, while width stays responsive.
    const rcContainer = screen.getByTestId("rc-container");
    expect(rcContainer.getAttribute("data-height")).toBe(
      String(parseInt(wrapper.style.height, 10)),
    );
    expect(rcContainer.getAttribute("data-width")).toBe("100%");
  });
});
