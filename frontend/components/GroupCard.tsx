"use client";

import { useRouter } from "next/navigation";
import type { Group, MatchSummary } from "@/lib/types";
import { groupHasLiveMatch } from "@/lib/liveLabel";
import { GroupTable } from "./GroupTable";

/** A whole-card link to the group detail page. The card itself handles
 *  navigation (role="link" + keyboard), so the team links inside the table can
 *  stay real <a>s without nesting <a> in <a>; those links stop propagation so a
 *  team click goes to the team, not the group. */
export function GroupCard({
  group,
  index = 0,
  matches,
}: {
  group: Group;
  index?: number;
  matches?: MatchSummary[];
}) {
  const router = useRouter();
  const href = `/groups/${group.id}`;
  const go = () => router.push(href);
  const live = groupHasLiveMatch(group.name, matches);

  return (
    <div
      role="link"
      tabIndex={0}
      aria-label={`${group.name}${live ? " — match in progress" : ""} — view matches and standings`}
      onClick={go}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          go();
        }
      }}
      style={{ animationDelay: `${Math.min(index * 40, 400)}ms` }}
      className="glass card-hover fade-up group cursor-pointer rounded-2xl p-4 sm:p-5"
    >
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <span className="font-display text-lg font-bold tracking-tight">{group.name}</span>
          {live && (
            <span
              className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-loss/15 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide text-loss"
              aria-hidden
            >
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-loss" />
              Live
            </span>
          )}
        </div>
        <span className="shrink-0 text-xs font-semibold text-muted transition group-hover:text-lime-deep">
          View matches <span aria-hidden>→</span>
        </span>
      </div>
      <GroupTable standings={group.standings} />
    </div>
  );
}
