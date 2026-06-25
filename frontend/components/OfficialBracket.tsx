"use client";

import Link from "next/link";
import { Flag } from "@/components/Flag";
import type { SideView, TieView } from "@/lib/officialBracket";
import { cn } from "@/lib/utils";

const ROUND_COLUMNS: { round: TieView["round"]; label: string; nos: number[] }[] = [
  { round: "r32", label: "Round of 32", nos: [73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 83, 84, 85, 86, 87, 88] },
  { round: "r16", label: "Round of 16", nos: [89, 90, 91, 92, 93, 94, 95, 96] },
  { round: "qf", label: "Quarter-finals", nos: [97, 98, 99, 100] },
  { round: "sf", label: "Semi-finals", nos: [101, 102] },
  { round: "final", label: "Final", nos: [104] },
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
        "flex items-center justify-between gap-2 py-0.5",
        s.isWinner ? "font-bold text-lime-deep" : s.team ? "text-foreground" : "text-muted",
      )}
    >
      <span className="flex min-w-0 items-center gap-1.5">
        {s.team ? <Flag team={s.team} size={18} /> : null}
        <span className="truncate text-sm">{s.team ?? s.label}</span>
      </span>
      {s.score != null ? (
        <span className="font-display text-sm font-extrabold tabular-nums">{s.score}</span>
      ) : null}
    </div>
  );
}

function TieCard({ v, roundLabel, final }: { v: TieView; roundLabel: string; final?: boolean }) {
  const live = v.state === "in_play";
  const body = (
    <div
      className={cn(
        "rounded-2xl p-3",
        final ? "panel-pitch" : "glass card-hover",
        live ? "ring-1 ring-loss/40" : "",
      )}
    >
      <div className="mb-1 flex items-center justify-between">
        <span className="text-[10px] font-bold uppercase tracking-wide text-muted">#{v.matchNo}</span>
        {live ? (
          <span
            className="inline-flex items-center gap-1.5 rounded-full bg-loss/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-loss"
            aria-label={`Live, ${v.liveLabel}`}
          >
            <span className="h-1.5 w-1.5 motion-safe:animate-pulse rounded-full bg-loss" aria-hidden />
            {v.liveLabel}
          </span>
        ) : v.state === "finished" ? (
          <span className="rounded-full bg-surface-2/70 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-muted">
            FT
          </span>
        ) : null}
      </div>
      <SideRow s={v.a} />
      <SideRow s={v.b} />
      {v.penaltyText ? (
        <div className="mt-1 text-[11px] font-semibold text-muted">{v.penaltyText}</div>
      ) : null}
    </div>
  );

  const linkable = v.matchId != null && v.state !== "labels";
  return (
    <li className="ko-tie min-w-[180px]" aria-label={tieAria(v, roundLabel)}>
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

export default function OfficialBracket({ ties }: { ties: Record<number, TieView> }) {
  const third = ties[103];
  return (
    <div className="space-y-4">
      <div
        className="flex items-stretch gap-6 overflow-x-auto pb-4 [scroll-snap-type:x_proximity] [-webkit-overflow-scrolling:touch]"
        aria-label="Official knockout bracket"
      >
        {ROUND_COLUMNS.map((col, idx) => (
          <div key={col.round} className="flex shrink-0 flex-col [scroll-snap-align:start]">
            <div className="mb-1 text-xs font-bold uppercase tracking-wide text-muted" aria-hidden>
              {col.label}
            </div>
            <ol
              aria-label={col.label}
              className={cn(
                "ko-round flex-1",
                idx === 0 && "ko-first",
                idx === ROUND_COLUMNS.length - 1 && "ko-last",
              )}
            >
              {col.nos.map((no) =>
                ties[no] ? (
                  <TieCard key={no} v={ties[no]} roundLabel={col.label} final={col.round === "final"} />
                ) : null,
              )}
            </ol>
          </div>
        ))}
      </div>

      {/* Detached 3rd-place node — NOT part of the converging tree, no connectors. */}
      {third ? (
        <div className="max-w-[200px]">
          <div className="mb-1 text-xs font-bold uppercase tracking-wide text-muted" aria-hidden>
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
