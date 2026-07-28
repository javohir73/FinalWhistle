import { render, screen } from "@testing-library/react";
import VenueCalibrationEvidencePage from "./page";

test("publishes reproducibility provenance and scope limits", () => {
  render(<VenueCalibrationEvidencePage />);
  expect(screen.getByRole("heading", { name: "World Cup venue calibration" })).toBeInTheDocument();
  expect(screen.getByText(/pipeline.publish_venue_audit/)).toBeInTheDocument();
  expect(screen.getByText(/seed 20260727/)).toBeInTheDocument();
  expect(screen.getByText(/pre-kickoff 1X2 only/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Return to the audit" })).toHaveAttribute("href", "/research/venue-calibration");
});
