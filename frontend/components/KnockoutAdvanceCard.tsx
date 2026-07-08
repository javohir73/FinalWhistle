import type { KnockoutAdvance } from "@/lib/types";
import { pct } from "@/lib/format";

/** "Who goes through" for an upcoming knockout tie (model v0.5).
 *
 *  The W/D/L bar above stops at the 90th minute; this section resolves the tie:
 *  a two-sided advance bar (no draw slice — someone must go through), each
 *  side's route split (in 90 / extra time / penalties, unconditional so the
 *  three sum to the side's advance probability), and the tie-level chance of
 *  extra time and a shootout. */
export function KnockoutAdvanceCard({
  knockout,
  home,
  away,
}: {
  knockout: KnockoutAdvance;
  home: string;
  away: string;
}) {
  const { p_advance_home: ph, p_advance_away: pa, paths } = knockout;
  const seg = (w: number) => ({ width: `${Math.max(0, w * 100)}%` });
  const rows: Array<{ label: string; key: keyof typeof paths.home }> = [
    { label: "in 90 minutes", key: "win_90" },
    { label: "in extra time", key: "win_et" },
    { label: "on penalties", key: "win_pens" },
  ];

  return (
    <div className="mt-5 border-t border-surface-2 pt-4">
      <span className="font-display text-[11px] font-semibold uppercase tracking-wider text-muted">
        Who goes through
      </span>
      <div
        className="mt-3 flex h-3 w-full gap-0.5 overflow-hidden rounded-full"
        role="img"
        aria-label={`${home} advance ${pct(ph)}, ${away} advance ${pct(pa)}`}
      >
        <div className="rounded-l-full bg-win" style={seg(ph)} />
        <div className="rounded-r-full bg-loss" style={seg(pa)} />
      </div>
      <div className="mt-2 flex justify-between text-[11px] font-semibold tabular-nums">
        <span className="text-lime-deep">{home} {pct(ph)}</span>
        <span className="text-loss">{away} {pct(pa)}</span>
      </div>
      <div className="mt-3 space-y-1">
        {rows.map(({ label, key }) => (
          <div
            key={key}
            className="grid grid-cols-[1fr_auto_1fr] items-center gap-2 text-xs tabular-nums"
          >
            <span className="text-right font-semibold">{pct(paths.home[key])}</span>
            <span className="w-28 text-center text-[11px] text-muted">{label}</span>
            <span className="text-left font-semibold">{pct(paths.away[key])}</span>
          </div>
        ))}
      </div>
      <p className="mt-3 text-[11px] leading-snug text-muted">
        A draw above means level after 90 minutes — {pct(knockout.p_extra_time)} chance
        this tie needs extra time, {pct(knockout.p_shootout)} that it reaches penalties.
      </p>
    </div>
  );
}
