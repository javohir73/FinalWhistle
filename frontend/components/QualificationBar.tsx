import { pct } from "@/lib/format";

/** Per-team qualification probability bar for the group tables. */
export function QualificationBar({ prob }: { prob: number | null }) {
  const value = prob ?? 0;
  const strong = value >= 0.5;
  return (
    <div className="flex items-center gap-2.5">
      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-surface-2">
        <div
          className="h-full rounded-full transition-all"
          style={{
            width: `${value * 100}%`,
            background: strong
              ? "linear-gradient(90deg, hsl(var(--win)/0.7), hsl(var(--win)))"
              : "hsl(var(--muted) / 0.6)",
          }}
        />
      </div>
      <span className="w-9 text-right text-xs font-semibold tabular-nums text-foreground/80">
        {pct(prob)}
      </span>
    </div>
  );
}
