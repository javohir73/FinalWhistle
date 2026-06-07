/** Persistent disclaimer shown on every page. */
export function DisclaimerBanner() {
  return (
    <div
      role="note"
      className="border-b border-gold/15 bg-gold/[0.04] px-4 py-1.5 text-center text-[11px] text-muted"
    >
      <span aria-hidden>⚠️</span> For analytics and entertainment only.{" "}
      <strong className="font-semibold text-foreground/80">Not betting advice.</strong>{" "}
      Predictions are probabilistic and never guaranteed.
    </div>
  );
}
