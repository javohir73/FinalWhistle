/** Persistent disclaimer shown on every page (PRD §4.3 req 18, §16). */
export function DisclaimerBanner() {
  return (
    <div
      role="note"
      className="bg-foreground/5 px-4 py-2 text-center text-xs text-foreground/70"
    >
      ⚠️ For analytics and entertainment only. <strong>Not betting advice.</strong>{" "}
      Predictions are probabilistic and never guaranteed.
    </div>
  );
}
