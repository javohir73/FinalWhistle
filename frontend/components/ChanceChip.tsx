import { cn } from "@/lib/utils";

/** Market-style probability chip: bold % plus an optional daily delta. */
export function ChanceChip({
  prob,
  deltaText,
  tone,
}: {
  prob: number;
  deltaText: string | null;
  tone: "up" | "down" | "muted";
}) {
  return (
    <span
      className={cn(
        "min-w-[58px] rounded-lg px-2 py-1 text-right text-sm font-extrabold tabular-nums",
        tone === "up" && "bg-win/10 text-lime-deep ring-1 ring-win/20",
        tone === "down" && "bg-loss/10 text-loss ring-1 ring-loss/20",
        tone === "muted" && "bg-surface-2 text-muted",
      )}
    >
      {Math.round(prob * 100)}%
      {deltaText ? <small className="block text-[9px] font-bold">{deltaText}</small> : null}
    </span>
  );
}
