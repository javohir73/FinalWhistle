import type { Availability } from "@/lib/types";

/** Availability context (announced XI or day-ahead injuries). Shows, per team, who
 *  is missing and the directional attack impact — explicitly NOT folded into the
 *  published probabilities (the adjusted forecast is logged for evaluation).
 *  Renders nothing until at least one signal — an announced XI or injury report —
 *  is available. */
export function AvailabilityNote({
  availability,
}: {
  availability: Availability | null | undefined;
}) {
  if (!availability?.has_lineup) return null;
  return (
    <section className="glass rounded-2xl p-6">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="font-display text-lg font-bold text-foreground">Availability</h2>
        <span className="inline-flex items-center gap-1.5 rounded-full bg-surface-2 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-muted">
          <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden />
          Experimental
        </span>
      </div>
      <ul className="space-y-1.5">
        {availability.per_team.map((t) => (
          <li key={t.side} className="text-sm leading-relaxed text-foreground">
            {t.note}
          </li>
        ))}
      </ul>
      <p className="mt-3 text-xs leading-relaxed text-muted">
        Availability context (announced XI or injuries) — not reflected in the number above; logged for evaluation.
      </p>
    </section>
  );
}
