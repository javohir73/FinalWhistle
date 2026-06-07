/** Odds comparison — stubbed in the MVP. Degrades gracefully so the UI is
 *  ready when odds are wired in a later phase. */
export function OddsCompare({ available }: { available: boolean }) {
  if (!available) {
    return (
      <div className="glass rounded-xl border-dashed p-5 text-sm text-muted">
        <span className="font-display font-semibold text-foreground/80">
          Bookmaker odds comparison
        </span>{" "}
        is coming in a later release — model-vs-market value detection.
      </div>
    );
  }
  return null;
}
