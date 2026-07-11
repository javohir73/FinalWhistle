import { ClubBadge } from "@/components/ClubBadge";
import type { NrlTeamForm } from "@/lib/types";
import type { IntelSectionProps } from "./sections";

const RESULT_TONE: Record<string, string> = {
  W: "bg-win/15 text-lime-deep",
  D: "bg-draw/15 text-amber-ink",
  L: "bg-loss/15 text-loss",
};

export function FormSection({ detail }: IntelSectionProps) {
  const { home, away } = detail.form;
  const { home: homeName, away: awayName } = detail.match;

  return (
    <div className="glass rounded-2xl p-6">
      <h2 className="mb-4 font-display text-lg font-bold text-foreground">Form &amp; head-to-head</h2>
      <div className="grid gap-4 sm:grid-cols-2">
        <TeamForm name={homeName} form={home} />
        <TeamForm name={awayName} form={away} />
      </div>

      {detail.h2h.length > 0 && (
        <div className="mt-5 border-t border-border pt-4">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted">
            Last {detail.h2h.length} meetings
          </p>
          <ul className="space-y-1.5 text-sm">
            {detail.h2h.map((meeting, i) => (
              <li key={i} className="flex items-center justify-between text-muted">
                <span>{meeting.home} vs {meeting.away}</span>
                <span className="font-semibold tabular-nums text-foreground">
                  {meeting.score_home}–{meeting.score_away}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function TeamForm({ name, form }: { name: string | null; form: NrlTeamForm | null }) {
  if (!form) return null;
  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <ClubBadge name={name} size={22} />
        <span className="font-display text-sm font-semibold">{name ?? "TBC"}</span>
      </div>
      <div className="flex gap-1">
        {form.last5.map((r, i) => (
          <span
            key={i}
            title={`Rd ${r.round ?? "?"} vs ${r.opponent}: ${r.for}–${r.against}`}
            className={`grid h-6 w-6 place-items-center rounded-md text-[11px] font-bold ${RESULT_TONE[r.result]}`}
          >
            {r.result}
          </span>
        ))}
      </div>
      <p className="mt-2 text-xs text-muted">
        Avg {form.avg_for}–{form.avg_against} · margin{" "}
        {form.avg_margin > 0 ? "+" : ""}
        {form.avg_margin}
      </p>
    </div>
  );
}
