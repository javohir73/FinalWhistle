import type { FormResult } from "@/lib/types";
import { cn } from "@/lib/utils";

const COLOR: Record<string, string> = {
  W: "bg-win",
  D: "bg-draw text-foreground",
  L: "bg-loss",
};

/** Colored W/D/L chips of a team's recent results (most recent first). */
export function FormStrip({ form }: { form: FormResult[] }) {
  if (!form.length) {
    return <p className="text-sm text-foreground/50">No recent matches.</p>;
  }
  return (
    <div className="flex flex-wrap gap-1.5">
      {form.map((f, i) => (
        <span
          key={i}
          title={`${f.result} vs ${f.opponent} ${f.score_for}–${f.score_against}`}
          className={cn(
            "flex h-7 w-7 items-center justify-center rounded text-xs font-bold text-white",
            COLOR[f.result],
          )}
        >
          {f.result}
        </span>
      ))}
    </div>
  );
}
