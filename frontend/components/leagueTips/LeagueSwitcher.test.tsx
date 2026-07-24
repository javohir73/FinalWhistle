import { fireEvent, render, screen } from "@testing-library/react";
import { LeagueSwitcher } from "./LeagueSwitcher";

it("renders a labeled pill per league, pressed on the current value", () => {
  render(<LeagueSwitcher leagues={["epl", "laliga", "bundesliga"]} value="laliga" onChange={jest.fn()} />);

  expect(screen.getByRole("button", { name: "Premier League" })).toHaveAttribute("aria-pressed", "false");
  expect(screen.getByRole("button", { name: "La Liga" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("button", { name: "Bundesliga" })).toHaveAttribute("aria-pressed", "false");
});

it("calls onChange with the clicked league's code", () => {
  const onChange = jest.fn();
  render(<LeagueSwitcher leagues={["epl", "laliga"]} value="epl" onChange={onChange} />);

  fireEvent.click(screen.getByRole("button", { name: "La Liga" }));
  expect(onChange).toHaveBeenCalledWith("laliga");
});
