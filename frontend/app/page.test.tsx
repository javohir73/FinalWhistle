import { render, screen } from "@testing-library/react";
import HomePage, { metadata } from "./page";

it("describes the platform rather than one competition", () => {
  expect(metadata.title).toBe("FinalWhistle — Sports predictions, clearly explained");
  expect(metadata.description).toContain("Football and NRL");
});

it("renders one clear route into every supported competition", () => {
  render(<HomePage />);

  expect(
    screen.getByRole("heading", { name: "Your matchday, all in one place." }),
  ).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Premier League/ })).toHaveAttribute(
    "href",
    "/football/epl",
  );
  expect(screen.getByRole("link", { name: /La Liga/ })).toHaveAttribute(
    "href",
    "/football/laliga",
  );
  expect(screen.getByRole("link", { name: /Bundesliga/ })).toHaveAttribute(
    "href",
    "/football/bundesliga",
  );
  expect(screen.getByRole("link", { name: /UEFA Champions League/ })).toHaveAttribute(
    "href",
    "/football/ucl",
  );
  expect(screen.getByRole("link", { name: /World Cup 2026/ })).toHaveAttribute(
    "href",
    "/football/wc26",
  );
  expect(screen.getByRole("link", { name: /National Rugby League/ })).toHaveAttribute(
    "href",
    "/nrl",
  );
});
