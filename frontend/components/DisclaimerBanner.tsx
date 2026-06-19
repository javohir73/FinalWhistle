/** Persistent disclaimer shown on every page. */
export function DisclaimerBanner() {
  return (
    <div
      role="note"
      className="border-b border-border bg-surface px-4 py-1.5 text-center text-[11px] text-muted"
    >
      <span aria-hidden className="text-draw">⚠️</span> For analytics and entertainment only.{" "}
      <strong className="font-semibold text-foreground">Not betting advice.</strong>{" "}
      Predictions are probabilistic and never guaranteed.
    </div>
  );
}
