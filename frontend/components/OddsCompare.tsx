/** Odds comparison — stubbed in the MVP (PRD Resolved Decision #1).
 *  Degrades gracefully so the UI is ready when odds are wired in Phase 4. */
export function OddsCompare({ available }: { available: boolean }) {
  if (!available) {
    return (
      <div className="rounded-lg border border-dashed border-border p-4 text-sm text-foreground/50">
        Bookmaker odds comparison is coming in a later release.
      </div>
    );
  }
  return null; // Real comparison rendered here once odds are available (Phase 4).
}
