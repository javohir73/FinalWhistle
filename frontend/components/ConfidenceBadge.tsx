import { cn } from "@/lib/utils";

const STYLES: Record<string, string> = {
  High: "text-lime-deep bg-win/15",
  Medium: "text-amber-ink bg-draw/15",
  Low: "text-loss bg-loss/15",
};

/** High/Medium/Low confidence pill — soft tinted background, small solid dot. */
export function ConfidenceBadge({ level }: { level: string | null }) {
  if (!level) return null;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide",
        STYLES[level] ?? "text-muted bg-surface-2",
      )}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden />
      {level} confidence
    </span>
  );
}
