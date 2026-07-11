"use client";

import Link from "next/link";
import type { Group, MatchSummary } from "@/lib/types";
import { groupHasLiveMatch } from "@/lib/liveLabel";
import { GroupTable } from "./GroupTable";

/** A whole-card link to the group detail page. The "View matches" text is a
 *  real <Link>, stretched via `after:absolute after:inset-0` to cover the
 *  whole card — that gives real anchor semantics (middle-click, copy-link,
 *  ctrl-click) without nesting <a> in <a>. The table sits above the stretched
 *  overlay (relative z-10) so its team links stay independently clickable. */
export function GroupCard({
  group,
  index = 0,
  matches,
}: {
  group: Group;
  index?: number;
  matches?: MatchSummary[];
}) {
  const href = `/groups/${group.id}`;
  const live = groupHasLiveMatch(group.name, matches);

  return (
    <div
      style={{ animationDelay: `${Math.min(index * 40, 400)}ms` }}
      className="glass card-hover fade-up group relative cursor-pointer rounded-2xl p-4 sm:p-5"
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
        <Link
          href={href}
          aria-label={`${group.name}${live ? " — match in progress" : ""} — view matches and standings`}
          className="shrink-0 text-xs font-semibold text-muted transition after:absolute after:inset-0 after:content-[''] group-hover:text-lime-deep"
        >
          View matches <span aria-hidden>→</span>
        </Link>
      </div>
      <div className="relative z-10">
        <GroupTable standings={group.standings} />
      </div>
    </div>
  );
}
