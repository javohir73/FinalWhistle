import { confidenceTier } from "./confidenceTier";

it("buckets a clear favourite (>=0.65) as High — 'biggest lock' territory", () => {
  expect(confidenceTier(0.65)).toBe("High"); // lower boundary, inclusive
  expect(confidenceTier(0.72)).toBe("High");
  expect(confidenceTier(1)).toBe("High");
});

it("buckets the middle band [0.5, 0.65) as Medium", () => {
  expect(confidenceTier(0.5)).toBe("Medium"); // lower boundary, inclusive
  expect(confidenceTier(0.58)).toBe("Medium");
  expect(confidenceTier(0.6499)).toBe("Medium"); // just under the High cut
});

it("buckets a near coin-flip (<0.5) as Low — 'closest call' territory", () => {
  expect(confidenceTier(0.4999)).toBe("Low"); // just under the Medium cut
  expect(confidenceTier(0.5 - Number.EPSILON)).toBe("Low");
  expect(confidenceTier(0)).toBe("Low");
});
