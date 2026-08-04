import { expectedMarginLabel } from "./format";

/** expected_margin is home-minus-away; the label must read as the favoured
 *  side so nobody needs to know the sign convention. */
describe("expectedMarginLabel", () => {
  it("names the home side for a positive margin", () => {
    expect(expectedMarginLabel(4.0, "Sharks", "Rabbitohs")).toBe("Sharks by 4.0");
  });
  it("names the away side for a negative margin", () => {
    expect(expectedMarginLabel(-5.5, "Wests Tigers", "Warriors")).toBe("Warriors by 5.5");
  });
  it("calls a zero margin dead level", () => {
    expect(expectedMarginLabel(0, "A", "B")).toBe("dead level");
  });
});
