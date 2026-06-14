/** The "Most important factors" chart was visually empty because its
 *  ResponsiveContainer measured a 0-height parent box and recharts drew
 *  nothing. The component now passes an explicit pixel height, so the chart
 *  always has a real box. recharts' own SVG text layout is unreliable under
 *  jsdom (it depends on text measurement jsdom can't do), so we stub recharts
 *  to a thin pass-through and assert on the data/labels the component itself
 *  derives — the human-readable factor name and its formatted weight — plus
 *  the non-zero inline height that is the actual fix. */
import { render, screen } from "@testing-library/react";

// Pass-through recharts: surface the data BarChart receives and the formatted
// value LabelList produces, so the component's label/percentage logic is
// visible to the DOM without relying on recharts' (jsdom-broken) SVG text.
jest.mock("recharts", () => {
  const React = require("react");
  // Capture the LabelList formatter from the most recent BarChart render so we
  // can apply it to each datum, mirroring what recharts draws beside each bar.
  let formatter: ((v: number) => string) | undefined;
  const collectFormatter = (children: React.ReactNode) => {
    React.Children.forEach(children, (child: any) => {
      if (!child || typeof child !== "object") return;
      if (child.props?.formatter && child.props?.dataKey === "weight") {
        formatter = child.props.formatter;
      }
      if (child.props?.children) collectFormatter(child.props.children);
    });
  };
  return {
    __esModule: true,
    ResponsiveContainer: ({ width, height, children }: any) =>
      React.createElement(
        "div",
        { "data-testid": "rc-container", "data-width": String(width), "data-height": String(height) },
        children,
      ),
    BarChart: ({ data, children }: any) => {
      collectFormatter(children);
      return React.createElement(
        "div",
        { "data-testid": "rc-barchart" },
        data.map((d: { name: string; weight: number }, i: number) =>
          React.createElement(
            "div",
            { key: i },
            React.createElement("span", null, d.name),
            React.createElement("span", null, formatter ? formatter(d.weight) : `${d.weight}`),
          ),
        ),
        children,
      );
    },
    Bar: ({ children }: any) => React.createElement(React.Fragment, null, children),
    Cell: () => null,
    LabelList: () => null,
    XAxis: () => null,
    YAxis: () => null,
  };
});

// eslint-disable-next-line import/first
import { FeatureImportanceChart } from "@/components/FeatureImportanceChart";

describe("FeatureImportanceChart", () => {
  it("renders human-readable factor labels with their weight values", () => {
    const { container } = render(
      <FeatureImportanceChart
        features={[
          { name: "elo_gap", weight: 0.66 },
          { name: "form_last10", weight: 0.2 },
        ]}
      />,
    );

    // The raw feature key is mapped to a friendly label…
    expect(screen.getByText("Elo gap")).toBeInTheDocument();
    expect(screen.getByText("Recent form")).toBeInTheDocument();
    // …and the 0–1 weight is rendered as a rounded percentage.
    expect(screen.getByText("66%")).toBeInTheDocument();
    expect(screen.getByText("20%")).toBeInTheDocument();

    // The fix: the wrapper carries an explicit, non-zero inline height so
    // recharts has a real box to draw into (height 0 was the empty section).
    const wrapper = container.firstElementChild as HTMLElement;
    expect(parseInt(wrapper.style.height, 10)).toBeGreaterThan(0);
    // And that same height is handed to the container instead of defaulting to
    // "100%" of a measured-0 parent.
    expect(screen.getByTestId("rc-container").getAttribute("data-height")).toBe(
      String(parseInt(wrapper.style.height, 10)),
    );
  });

  it("renders nothing when there are no features", () => {
    const { container } = render(<FeatureImportanceChart features={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
