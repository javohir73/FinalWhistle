import { render, screen } from "@testing-library/react";
import { MatchWriteup } from "@/components/MatchWriteup";

const writeup = {
  case_home: "The model gives England a 50% chance of winning in 90 minutes.",
  case_away: "The model gives Norway a 24% chance of winning in 90 minutes.",
  call: "England to win — 50% in 90 minutes, with 2–1 the single most likely scoreline (about 11%).",
  caveat: "A draw after 90 minutes is live at roughly one in 4 (26%).",
};

test("renders all four labelled sections", () => {
  render(<MatchWriteup home="England" away="Norway" writeup={writeup} />);
  expect(screen.getByText("The case for England")).toBeInTheDocument();
  expect(screen.getByText("The case for Norway")).toBeInTheDocument();
  expect(screen.getByText("The call")).toBeInTheDocument();
  expect(screen.getByText("The honest caveat")).toBeInTheDocument();
  expect(screen.getByText(/2–1 the single most likely scoreline/)).toBeInTheDocument();
});

test("renders nothing without a writeup", () => {
  const { container } = render(
    <MatchWriteup home="England" away="Norway" writeup={null} />,
  );
  expect(container).toBeEmptyDOMElement();
});
