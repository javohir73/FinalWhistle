import { isKnockout, type Verdict } from "@/lib/verdict";

/** Footnote under a finished knockout verdict. The model predicts regulation
 *  (90 min) only, so when a tie was level after 90 and decided on penalties this
 *  reconciles the AI's call with who actually advanced — otherwise "Exact score"
 *  next to the losing side reads as a contradiction. Renders nothing unless a
 *  shootout decided the match. */
export function ShootoutNote({ verdict }: { verdict: Verdict | null }) {
  if (!verdict?.shootout) return null;
  return (
    <p className="mt-1.5 w-full text-[11px] leading-snug text-muted">
      Level after 90 — {verdict.shootout.text}. Shootouts aren&apos;t modelled.
    </p>
  );
}

/** Pre-match footnote for an upcoming/live knockout tie: the draw slice of the
 *  probability bar means "level after 90 minutes", after which the real match
 *  continues to extra time and penalties — outcomes the model doesn't predict.
 *  Renders nothing for group games, where a draw is a final result. */
export function KnockoutDrawNote({ stage }: { stage: string | null | undefined }) {
  if (!stage || !isKnockout(stage)) return null;
  return (
    <p className="mt-2 text-[11px] leading-snug text-muted">
      Draw = level after 90 minutes. As a knockout tie it would then go to extra
      time and penalties, which the ML model doesn&apos;t predict.
    </p>
  );
}

/** The "90 min" qualifier chip for a knockout verdict — clarifies the AI call is
 *  for regulation time. Renders nothing for group games. */
export function BasisTag({ verdict }: { verdict: Verdict | null }) {
  if (!verdict?.basis) return null;
  return (
    <span className="ml-1.5 rounded bg-surface-2 px-1 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted">
      {verdict.basis}
    </span>
  );
}
