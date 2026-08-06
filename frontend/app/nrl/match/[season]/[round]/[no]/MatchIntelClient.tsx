"use client";

import { useState } from "react";
import { sections } from "./sections";
import type { NrlMatchDetail, NrlProbHistory } from "@/lib/types";

/** Sticky section-pill nav + section renderer, driven entirely by the
 *  `sections` array -- Waves 2/3 extend the page by appending to that array,
 *  never by editing this file. */
export function MatchIntelClient({
  detail,
  probHistory,
}: {
  detail: NrlMatchDetail;
  probHistory: NrlProbHistory | null;
}) {
  const [active, setActive] = useState(sections[0]?.id ?? "");

  return (
    <div className="space-y-6">
      {detail.prediction?.predicted_total != null && detail.prediction.predicted_score != null && (
        <div className="flex justify-center">
          <div className="rounded-xl border border-border bg-surface-2 px-3 py-2 text-center">
            <p className="text-note font-bold uppercase tracking-wider text-muted">
              Predicted score
            </p>
            <p className="mt-0.5 text-sm font-extrabold tabular-nums text-foreground">
              {detail.match.home} {detail.prediction.predicted_score.home}–
              {detail.prediction.predicted_score.away} {detail.match.away}
            </p>
            <p className="mt-0.5 text-label font-semibold tabular-nums text-muted">
              {Math.round(detail.prediction.predicted_total)} total points
            </p>
          </div>
        </div>
      )}

      <nav
        aria-label="Match sections"
        className="sticky top-0 z-10 -mx-4 flex gap-1 overflow-x-auto bg-background/95 px-4 py-2 backdrop-blur"
      >
        {sections.map((s) => (
          <a
            key={s.id}
            href={`#${s.id}`}
            onClick={() => setActive(s.id)}
            className={
              active === s.id
                ? "shrink-0 rounded-full bg-win/15 px-3 py-1.5 text-xs font-semibold text-lime-deep"
                : "shrink-0 rounded-full bg-surface-2 px-3 py-1.5 text-xs font-semibold text-muted hover:text-foreground"
            }
          >
            {s.label}
          </a>
        ))}
      </nav>

      {sections.map((s) => {
        const Section = s.render;
        return (
          <section key={s.id} id={s.id} className="scroll-mt-16">
            <Section detail={detail} probHistory={probHistory} />
          </section>
        );
      })}
    </div>
  );
}
