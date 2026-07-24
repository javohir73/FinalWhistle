import { render, screen } from "@testing-library/react";
// jsdom's CSSOM rejects `hsl(var(--x))` as an unparseable color (it silently
// drops the whole style, live-DOM only) -- react-dom's static-markup renderer
// serializes the style prop as a plain string instead, so it's the only way
// to actually see the inline style this component sets. Used for the
// accent-var assertion below only; the plain-text Eyebrow case renders fine
// through the normal RTL path.
import { renderToStaticMarkup } from "react-dom/server.node";
import { Eyebrow, CompEyebrowChip } from "@/components/Eyebrow";

describe("Eyebrow", () => {
  it("renders its text at the 11px a11y floor, uppercased by CSS", () => {
    render(<Eyebrow>Tonight feature</Eyebrow>);
    const label = screen.getByText("Tonight feature");
    expect(label).toHaveClass("uppercase");
    expect(label).toHaveClass("text-[11px]");
  });
});

describe("CompEyebrowChip", () => {
  it("renders the EPL short label with the epl accent var and >=11px text", () => {
    const html = renderToStaticMarkup(<CompEyebrowChip comp="epl" />);
    expect(html).toContain(">EPL<");
    expect(html).toContain("text-[11px]");
    expect(html).toContain("--accent-epl");
  });
});
