import { cn } from "@/lib/utils";

type Confidence = "High" | "Medium" | "Low" | null;

/** Confidence tier → ring accent token. The arc LENGTH encodes probability;
 *  the arc COLOUR encodes the tier — two independent signals. Both the % and
 *  the tier WORD are printed, so colour is never the sole carrier. */
const ACCENT: Record<Exclude<Confidence, null>, string> = {
  High: "hsl(var(--confidence-high))",
  Medium: "hsl(var(--confidence-medium))",
  Low: "hsl(var(--confidence-low))",
};

/** Confidence WORD styling. Amber (Medium) prints >=12px bold to clear the
 *  amber-text floor; High lime, Low muted. */
const WORD: Record<Exclude<Confidence, null>, string> = {
  High: "text-lime-deep text-xs font-bold",
  Medium: "text-amber-ink text-xs font-bold",
  Low: "text-muted text-[11px] font-semibold",
};

/**
 * ConfidenceRing — conic % dial for the headline prediction (P4 scope item 3).
 * The ring arc encodes `probability` (0..1, the leading outcome's chance —
 * the caller picks the max of the shown W/D/L); the ring colour encodes the
 * confidence tier. The centre prints the rounded %, and the tier WORD sits
 * beneath it, so the ring never carries meaning by colour alone.
 *
 * Pure CSS, deterministic, no hooks — safe to render server-side. No animation.
 */
export function ConfidenceRing({
  probability,
  confidence,
  outcomeLabel,
  size = 76,
}: {
  probability: number;
  confidence: Confidence;
  outcomeLabel?: string;
  size?: number;
}) {
  const pct = Math.round(probability * 100);
  const accent = confidence ? ACCENT[confidence] : "hsl(var(--muted))";
  const word = confidence ? WORD[confidence] : "text-muted text-[11px] font-semibold";
  const inner = size - 14;

  return (
    <div
      role="img"
      aria-label={`${outcomeLabel ?? "Headline prediction"} ${pct}%, ${confidence ?? "unrated"} confidence`}
      className="relative inline-flex shrink-0 items-center justify-center"
      style={{
        width: size,
        height: size,
        borderRadius: "9999px",
        background: `conic-gradient(${accent} ${probability * 100}%, hsl(var(--border)) 0)`,
      }}
    >
      <div
        className="absolute flex flex-col items-center justify-center rounded-full [background:hsl(var(--surface))]"
        style={{ width: inner, height: inner }}
      >
        <span className="font-display text-2xl font-extrabold leading-none tabular-nums">
          {pct}
          <span className="text-[0.5em] align-top">%</span>
        </span>
        <span className={cn("mt-0.5 uppercase leading-none tracking-wide", word)}>
          {confidence ? confidence.toUpperCase() : "—"}
        </span>
      </div>
    </div>
  );
}
