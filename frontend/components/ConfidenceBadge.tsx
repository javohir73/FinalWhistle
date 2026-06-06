import { cn } from "@/lib/utils";

const STYLES: Record<string, string> = {
  High: "bg-win/15 text-win",
  Medium: "bg-draw/15 text-draw",
  Low: "bg-loss/15 text-loss",
};

const DOT: Record<string, string> = { High: "🟢", Medium: "🟡", Low: "🔴" };

/** High/Medium/Low confidence pill. */
export function ConfidenceBadge({ level }: { level: string | null }) {
  if (!level) return null;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
        STYLES[level] ?? "bg-foreground/10 text-foreground/60",
      )}
    >
      <span aria-hidden>{DOT[level]}</span>
      {level} confidence
    </span>
  );
}
