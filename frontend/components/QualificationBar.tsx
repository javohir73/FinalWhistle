import { pct } from "@/lib/format";

/** Per-team qualification probability bar for the group tables. */
export function QualificationBar({ prob }: { prob: number | null }) {
  const value = prob ?? 0;
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-20 overflow-hidden rounded-full bg-foreground/10">
        <div className="h-full rounded-full bg-win" style={{ width: `${value * 100}%` }} />
      </div>
      <span className="w-9 text-right text-xs tabular-nums text-foreground/70">
        {pct(prob)}
      </span>
    </div>
  );
}
