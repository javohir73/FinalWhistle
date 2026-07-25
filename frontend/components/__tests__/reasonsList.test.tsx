import { render, screen } from "@testing-library/react";
import { ReasonsList } from "@/components/ReasonsList";

test("renders each reason with a leading + marker", () => {
  const reasons = [
    "England rank higher on the model's strength rating.",
    "Home advantage nudges the win probability up.",
    "Recent form favours the hosts.",
  ];
  render(<ReasonsList reasons={reasons} />);
  for (const r of reasons) {
    expect(screen.getByText(r)).toBeInTheDocument();
  }
  expect(screen.getAllByText("+")).toHaveLength(reasons.length);
});

test("renders an empty list without throwing when there are no reasons", () => {
  const { container } = render(<ReasonsList reasons={[]} />);
  expect(container.querySelectorAll("li")).toHaveLength(0);
  expect(screen.queryByText("+")).not.toBeInTheDocument();
});
