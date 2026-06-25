"use client";

import Link from "next/link";
import { Flag } from "@/components/Flag";
import { KO_TREE, FINAL_MATCH, THIRD_PLACE } from "@/lib/bracketStructure";
import type { SideView, TieView } from "@/lib/officialBracket";
import { cn } from "@/lib/utils";

const ROUND_LABEL: Record<string, string> = {
  r32: "Round of 32",
  r16: "Round of 16",
  qf: "Quarter-finals",
  sf: "Semi-finals",
};

/** Split the bracket into its two halves from the winner-feeder map, so the tree
 *  converges from BOTH sides toward the Final in the centre — the classic printed
 *  layout that fits on one screen — instead of one tall left-to-right column. */
function half(sfNo: number) {
  const sf = [sfNo];
  const qf = KO_TREE[sfNo]; // [97,98] / [99,100]
  const r16 = qf.flatMap((m) => KO_TREE[m]); // 4
  const r32 = r16.flatMap((m) => KO_TREE[m]); // 8
  return { r32, r16, qf, sf };
}
const L = half(101);
const R = half(102);
// Column order outer→inner. Left half flows rightward; right half flows leftward.
const LEFT_COLS: [string, number[]][] = [
  ["r32", L.r32],
  ["r16", L.r16],
  ["qf", L.qf],
  ["sf", L.sf],
];
const RIGHT_COLS: [string, number[]][] = [
  ["sf", R.sf],
  ["qf", R.qf],
  ["r16", R.r16],
  ["r32", R.r32],
];

function sideAria(s: SideView): string {
  const name = s.team ?? s.label;
  const score = s.score != null ? ` ${s.score}` : "";
  return `${name}${score}`;
}

function tieAria(v: TieView, roundLabel: string): string {
  const a = sideAria(v.a);
  const b = sideAria(v.b);
  const winner =
    v.a.isWinner ? `, ${v.a.team ?? v.a.label} win` : v.b.isWinner ? `, ${v.b.team ?? v.b.label} win` : "";
  return `${roundLabel}: ${a} vs ${b}, ${v.state}${winner}`;
}

function SideRow({ s }: { s: SideView }) {
  return (
    <div
      data-side
      className={cn(
        "flex items-center justify-between gap-1.5 py-0.5",
        s.isWinner ? "font-bold text-lime-deep" : s.team ? "text-foreground" : "text-muted",
      )}
    >
      <span className="flex min-w-0 items-center gap-1">
        {s.team ? <Flag team={s.team} size={15} /> : null}
        <span className="truncate text-[11px] leading-tight">{s.team ?? s.label}</span>
      </span>
      {s.score != null ? (
        <span className="font-display text-[11px] font-extrabold tabular-nums">{s.score}</span>
      ) : null}
    </div>
  );
}

function TieCard({ v, roundLabel, accent }: { v: TieView; roundLabel: string; accent?: boolean }) {
  const live = v.state === "in_play";
  const body = (
    <div
      className={cn(
        "rounded-xl px-2 py-1.5",
        accent ? "panel-pitch" : "glass card-hover",
        live ? "ring-1 ring-loss/40" : "",
      )}
    >
      <div className="flex items-center justify-between leading-none">
        <span className="text-[8px] font-bold uppercase tracking-wide text-muted">#{v.matchNo}</span>
        {live ? (
          <span
            className="inline-flex items-center gap-1 rounded-full bg-loss/15 px-1.5 py-0.5 text-[8px] font-bold uppercase tracking-wide text-loss"
            aria-label={`Live, ${v.liveLabel}`}
          >
            <span className="h-1 w-1 motion-safe:animate-pulse rounded-full bg-loss" aria-hidden />
            {v.liveLabel}
          </span>
        ) : v.state === "finished" ? (
          <span className="rounded-full bg-surface-2/70 px-1.5 py-0.5 text-[8px] font-bold uppercase tracking-wide text-muted">
            FT
          </span>
        ) : null}
      </div>
      <SideRow s={v.a} />
      <SideRow s={v.b} />
      {v.penaltyText ? (
        <div className="mt-0.5 text-[9px] font-semibold text-muted">{v.penaltyText}</div>
      ) : null}
    </div>
  );

  const linkable = v.matchId != null && v.state !== "labels";
  return (
    <li className="ko-tie w-[108px]" aria-label={tieAria(v, roundLabel)}>
      {linkable ? (
        <Link href={`/match/${v.matchId}`} className="block">
          {body}
        </Link>
      ) : (
        <div>{body}</div>
      )}
    </li>
  );
}

function Column({
  side,
  round,
  nos,
  ties,
  outer,
}: {
  side: "l" | "r";
  round: string;
  nos: number[];
  ties: Record<number, TieView>;
  outer: boolean;
}) {
  const label = ROUND_LABEL[round];
  return (
    <div className="flex shrink-0 flex-col">
      <div className="mb-1 text-center text-[10px] font-bold uppercase tracking-wide text-muted" aria-hidden>
        {label}
      </div>
      <ol
        aria-label={`${label}, ${side === "l" ? "left" : "right"} half`}
        className={cn("ko-round flex-1", side === "l" ? "ko-col-l" : "ko-col-r", outer && "ko-edge")}
      >
        {nos.map((no) => (ties[no] ? <TieCard key={no} v={ties[no]} roundLabel={label} /> : null))}
      </ol>
    </div>
  );
}

export default function OfficialBracket({ ties }: { ties: Record<number, TieView> }) {
  const final = ties[FINAL_MATCH];
  const third = ties[THIRD_PLACE.no];
  return (
    <div className="space-y-3">
      <div className="overflow-x-auto pb-3 [scroll-snap-type:x_proximity] [-webkit-overflow-scrolling:touch]">
      <div
        className="ko-bracket mx-auto flex w-max items-stretch gap-3"
        aria-label="Official knockout bracket"
      >
        {LEFT_COLS.map(([round, nos], i) => (
          <Column key={`l-${round}`} side="l" round={round} nos={nos} ties={ties} outer={i === 0} />
        ))}

        {/* Centre: the Final, vertically centred so both semi-finals meet it. */}
        <div className="flex shrink-0 flex-col">
          <div className="mb-1 text-center text-[10px] font-bold uppercase tracking-wide text-muted" aria-hidden>
            Final
          </div>
          <ol aria-label="Final" className="ko-round flex-1">
            {final ? <TieCard v={final} roundLabel="Final" accent /> : null}
          </ol>
        </div>

        {RIGHT_COLS.map(([round, nos], i) => (
          <Column
            key={`r-${round}`}
            side="r"
            round={round}
            nos={nos}
            ties={ties}
            outer={i === RIGHT_COLS.length - 1}
          />
        ))}
      </div>
      </div>

      {/* Detached 3rd-place node — centred under the Final, not part of the tree. */}
      {third ? (
        <div className="mx-auto w-[140px]">
          <div className="mb-1 text-center text-[10px] font-bold uppercase tracking-wide text-muted" aria-hidden>
            Third place
          </div>
          <ol aria-label="Third place">
            <TieCard v={third} roundLabel="Third place" />
          </ol>
        </div>
      ) : null}
    </div>
  );
}
