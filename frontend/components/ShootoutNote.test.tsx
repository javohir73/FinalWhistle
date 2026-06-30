/** ShootoutNote / BasisTag: the regulation-time qualifier and the penalty
 *  footnote that reconcile a 90-min prediction with a knockout decided on pens. */
import { render, screen } from "@testing-library/react";
import { ShootoutNote, BasisTag } from "./ShootoutNote";
import type { Verdict } from "@/lib/verdict";

const group: Verdict = { kind: "exact", label: "Exact score predicted", basis: null, shootout: null };
const koReg: Verdict = { kind: "winner", label: "Result predicted right", basis: "90 min", shootout: null };
const koPens: Verdict = {
  kind: "exact",
  label: "Exact score predicted",
  basis: "90 min",
  shootout: { winner: "Morocco", text: "Morocco won 3–2 on penalties" },
};

describe("BasisTag", () => {
  it("shows the 90-min qualifier for knockout verdicts", () => {
    render(<BasisTag verdict={koReg} />);
    expect(screen.getByText("90 min")).toBeInTheDocument();
  });
  it("renders nothing for group matches or a null verdict", () => {
    const { container, rerender } = render(<BasisTag verdict={group} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<BasisTag verdict={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("ShootoutNote", () => {
  it("notes who advanced on penalties and that shootouts aren't modelled", () => {
    render(<ShootoutNote verdict={koPens} />);
    expect(screen.getByText(/Morocco won 3–2 on penalties/)).toBeInTheDocument();
    expect(screen.getByText(/Shootouts aren't modelled/)).toBeInTheDocument();
  });
  it("renders nothing when the match wasn't decided on penalties", () => {
    const { container } = render(<ShootoutNote verdict={koReg} />);
    expect(container).toBeEmptyDOMElement();
  });
  it("renders nothing for a null verdict", () => {
    const { container } = render(<ShootoutNote verdict={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
