import { render, screen } from "@testing-library/react";
import VenueCalibrationPage from "./page";

test("publishes the honest verdict, scope boundary, and reproducibility command", () => {
  render(<VenueCalibrationPage />);

  expect(screen.getByText(/credibly behind Kalshi/i)).toBeInTheDocument();
  expect(screen.getByText(/not evidence that the model won/i)).toBeInTheDocument();
  expect(screen.getByText(/nothing yet about in-play prices/i)).toBeInTheDocument();
  expect(screen.getByText(/useful for robustness/i)).toBeInTheDocument();
  expect(screen.getByText(/pipeline.publish_venue_audit/i)).toBeInTheDocument();
  expect(screen.getByText(/not betting advice/i)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "evidence card" })).toHaveAttribute(
    "href",
    "/research/venue-calibration/evidence",
  );
});
