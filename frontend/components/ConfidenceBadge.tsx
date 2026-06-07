import { cn } from "@/lib/utils";

const STYLES: Record<string, string> = {
  High: "text-win ring-win/30 bg-win/10",
  Medium: "text-draw ring-draw/30 bg-draw/10",
  Low: "text-loss ring-loss/30 bg-loss/10",
};

/** High/Medium/Low confidence pill with a glowing status dot. */
export function ConfidenceBadge({ level }: { level: string | null }) {
  if (!level) return null;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide ring-1",
        STYLES[level] ?? "text-muted ring-border bg-surface-2",
      )}
    >
      <span
        className="h-1.5 w-1.5 rounded-full bg-current shadow-[0_0_8px_currentColor]"
        aria-hidden
      />
      {level} confidence
    </span>
  );
}
