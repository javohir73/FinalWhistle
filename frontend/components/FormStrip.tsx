import type { FormResult } from "@/lib/types";
import { cn } from "@/lib/utils";

const COLOR: Record<string, string> = {
  W: "bg-win/15 text-win ring-win/30",
  D: "bg-draw/15 text-draw ring-draw/30",
  L: "bg-loss/15 text-loss ring-loss/30",
};

/** Colored W/D/L chips of a team's recent results (most recent first). */
export function FormStrip({ form }: { form: FormResult[] }) {
  if (!form.length) {
    return <p className="text-sm text-muted">No recent matches.</p>;
  }
  return (
    <div className="flex flex-wrap gap-1.5">
      {form.map((f, i) => (
        <span
          key={i}
          title={`${f.result} vs ${f.opponent} ${f.score_for}–${f.score_against}`}
          className={cn(
            "grid h-8 w-8 place-items-center rounded-lg text-xs font-bold ring-1",
            COLOR[f.result],
          )}
        >
          {f.result}
        </span>
      ))}
    </div>
  );
}
