"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getIntel } from "@/lib/api";
import type { IntelMatch, IntelResponse, IntelStoryline } from "@/lib/types";
import { MoversPanel } from "@/components/MoversPanel";

const pct = (p: number) => `${Math.round(p * 100)}%`;

/** Disagreement worth calling out: market and model ≥5 points apart. */
const DISAGREE_PTS = 0.05;

/** "Argentina to win the Cup" / "France to win the match". */
export function storylineLabel(
  s: IntelStoryline,
  sport: "football" | "nrl",
): string {
  const name = s.team?.name ?? "—";
  if (s.market_type === "title_winner") {
    return `${name} to win the ${sport === "football" ? "Cup" : "Premiership"}`;
  }
  return `${name} to win the match`;
}

/** "23m ago" / "3h ago" for the provenance footer. */
export function minutesAgo(iso: string, now: Date = new Date()): string {
  const mins = Math.max(0, Math.round((now.getTime() - new Date(iso).getTime()) / 60000));
  return mins < 60 ? `${mins}m ago` : `${Math.round(mins / 60)}h ago`;
}

const SOURCE_LABELS: Record<string, string> = {
  polymarket: "Polymarket",
  kalshi: "Kalshi",
};

/** "Polymarket" / "Polymarket · Kalshi" — built from the sources actually
 *  present in this response, not a fixed list. A source that contributed no
 *  rows this run (e.g. a dead Kalshi series) must not be claimed here. */
export function sourcesFooter(intel: IntelResponse): string {
  const sources = new Set<string>();
  intel.matches.forEach((m) => m.market.forEach((mk) => sources.add(mk.source)));
  intel.storylines.forEach((s) => sources.add(s.source));
  return Array.from(sources)
    .sort()
    .map((s) => SOURCE_LABELS[s] ?? s)
    .join(" · ");
}

function MatchRow({ m, sport }: { m: IntelMatch; sport: "football" | "nrl" }) {
  const market = m.market[0];
  const disagree =
    m.disagreement !== null && Math.abs(m.disagreement) >= DISAGREE_PTS;
  // NRL match pages are keyed by (season, round, match_no) — not by the
  // sport_matches id this payload carries — so only football rows link out.
  const Body = sport === "football" ? Link : "div";
  return (
    <li className="border-t border-white/10 py-2.5 first:border-t-0">
      <Body href={`/match/${m.match_id}`} className="block">
        <span className="font-display text-[15px] font-semibold text-white">
          {m.home?.name ?? "TBD"} vs {m.away?.name ?? "TBD"}
        </span>
        <span className="mt-0.5 block text-[12px] font-medium text-white/60">
          Market {pct(market.home)}
          {market.draw !== null ? ` · draw ${pct(market.draw)}` : ""} ·{" "}
          {pct(market.away)}
        </span>
        {m.model ? (
          <span className="block text-[12px] font-medium text-white/45">
            Model {pct(m.model.home)}
            {m.model.draw !== null ? ` · draw ${pct(m.model.draw)}` : ""} ·{" "}
            {pct(m.model.away)}
            {disagree ? (
              <span className="ml-2 font-semibold text-win">
                market {m.disagreement! > 0 ? "higher" : "lower"} on{" "}
                {m.home?.name ?? "home"}
              </span>
            ) : null}
          </span>
        ) : null}
      </Body>
    </li>
  );
}

/** Dashboard hero (spec 2026-07-10): prediction-market odds vs our model for
 *  the next fixtures + the biggest 24h market moves. Falls back to the movers
 *  panel whenever the sport has no fresh market data or the fetch fails. */
export function IntelPanel({ sport }: { sport: "football" | "nrl" }) {
  const [intel, setIntel] = useState<IntelResponse | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    setIntel(null);
    setFailed(false);
    getIntel(sport)
      .then((res) => {
        if (active) setIntel(res);
      })
      .catch(() => {
        if (active) setFailed(true);
      });
    return () => {
      active = false;
    };
  }, [sport]);

  if (failed || (intel !== null && !intel.has_data)) {
    return <MoversPanel sport={sport} />;
  }

  return (
    <section className="panel-pitch mt-6 rounded-2xl p-5">
      <p className="font-display text-[11px] font-semibold uppercase tracking-[0.2em] text-white/60">
        Market intel
      </p>
      {intel === null ? (
        <div className="skeleton mt-4 h-32 rounded-xl" aria-hidden="true" />
      ) : (
        <>
          <ul className="mt-2">
            {intel.matches.map((m) => (
              <MatchRow key={m.match_id} m={m} sport={sport} />
            ))}
          </ul>
          {intel.storylines.length > 0 ? (
            <ul className="mt-3 border-t border-white/10 pt-2">
              {intel.storylines.map((s) => (
                <li
                  key={`${s.market_type}-${s.match_id ?? s.team?.id}-${s.outcome}`}
                  className="py-1 text-[12px] font-medium text-white/60"
                >
                  {storylineLabel(s, sport)}{" "}
                  <span className={s.prob_to >= s.prob_from ? "text-win" : "text-loss"}>
                    {pct(s.prob_from)} → {pct(s.prob_to)}
                  </span>{" "}
                  <span className="text-white/35">
                    in {s.window_hours}h · {s.source}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
          {intel.updated_at ? (
            <p className="mt-2 text-[11px] font-medium text-white/35">
              {sourcesFooter(intel) ? `via ${sourcesFooter(intel)} · ` : ""}updated {minutesAgo(intel.updated_at)}
            </p>
          ) : null}
        </>
      )}
    </section>
  );
}
