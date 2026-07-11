"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getMovers } from "@/lib/api";
import type { Mover } from "@/lib/types";
import { ChanceChip } from "@/components/ChanceChip";
import { Sparkline } from "@/components/Sparkline";

/** Reader copy for market codes; falls back for future markets. */
export function marketLabel(market: string): string {
  switch (market) {
    case "make_knockout":
      return "to reach the knockouts";
    case "win_title":
      return "to win the Cup";
    case "qualify_group":
      return "to qualify from the group";
    case "win_match":
      return "to win this round";
    default:
      return "probability";
  }
}

/** "▲ 2.4" / "▼ 1.6" in percentage points; null with <2 snapshot days. */
export function formatDelta(delta: number | null): string | null {
  if (delta === null) return null;
  const pts = Math.abs(delta * 100).toFixed(1);
  return `${delta >= 0 ? "▲" : "▼"} ${pts}`;
}

/** Home hero (replaces the "Your team" panel, spec 2026-07-09): the three
 *  biggest probability swings since the previous model refresh. */
export function MoversPanel({ sport }: { sport: "football" | "nrl" }) {
  const [movers, setMovers] = useState<Mover[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    setMovers(null);
    setFailed(false);
    getMovers(sport)
      .then((res) => {
        if (active) setMovers(res.movers);
      })
      .catch(() => {
        if (active) setFailed(true);
      });
    return () => {
      active = false;
    };
  }, [sport]);

  if (failed || (movers !== null && movers.length === 0)) return null;

  return (
    <section className="panel-pitch mt-6 rounded-2xl p-5">
      <p className="font-display text-[11px] font-semibold uppercase tracking-[0.2em] text-white/60">
        Today&apos;s movers
      </p>
      {movers === null ? (
        <div className="skeleton mt-4 h-32 rounded-xl" aria-hidden="true" />
      ) : (
        <ul className="mt-2">
          {movers.map((m) => {
            const up = (m.delta ?? 0) >= 0;
            const rowInner = (
              <>
                <span className="flex-1">
                  <span className="font-display text-[15px] font-semibold text-white">
                    {m.name}
                  </span>
                  <span className="block text-[11px] font-medium text-white/45">
                    {marketLabel(m.market)}
                  </span>
                </span>
                <Sparkline values={m.series} tone={up ? "up" : "down"} />
                <ChanceChip
                  prob={m.prob}
                  deltaText={formatDelta(m.delta)}
                  tone={m.delta === null ? "muted" : up ? "up" : "down"}
                />
              </>
            );
            return (
              <li
                key={`${m.entity_id}-${m.market}`}
                className="flex items-center gap-3 border-t border-white/10 py-2.5 first:border-t-0"
              >
                {m.match_url ? (
                  <Link href={m.match_url} className="flex flex-1 items-center gap-3">
                    {rowInner}
                  </Link>
                ) : (
                  <div className="flex flex-1 items-center gap-3">{rowInner}</div>
                )}
              </li>
            );
          })}
        </ul>
      )}
      <Link
        href={sport === "nrl" ? "/nrl/matches" : "/matches"}
        className="mt-2 inline-block text-sm font-semibold text-win"
      >
        All fixtures →
      </Link>
    </section>
  );
}
