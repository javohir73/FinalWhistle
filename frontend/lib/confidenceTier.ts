/** The three confidence tiers the shipped ConfidenceRing colours by. Kept as a
 *  named alias (rather than reaching into ConfidenceRing's local type) so callers
 *  that only need the tier, not the ring, don't import a component. */
export type ConfidenceTier = "High" | "Medium" | "Low";

/**
 * Map a model pick's confidence (0..1, the favoured side's chance) to the tier
 * the ConfidenceRing colours by. Unlike the match-centre confidence, which the
 * API hands down already tiered, NRL `pick_confidence` is a bare probability —
 * this is the one place that buckets it.
 *
 * Thresholds mirror how TipsheetBlock frames a round in words: its "biggest
 * lock" is the highest-confidence pick and its "closest call" the lowest. NRL
 * picks are effectively two-way (draws are rare), so 0.5 is the floor of a
 * favoured pick — a call sitting near it is a coin-flip ("closest call" → Low).
 * 0.65 marks a clear favourite, lock territory (→ High); the band between is
 * Medium. Pure and deterministic — safe to call server-side.
 */
export function confidenceTier(probability: number): ConfidenceTier {
  if (probability >= 0.65) return "High";
  if (probability >= 0.5) return "Medium";
  return "Low";
}
