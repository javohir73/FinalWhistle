"use client";

import { useRouter } from "next/navigation";
import type { Group } from "@/lib/types";
import { GroupTable } from "./GroupTable";

/** A whole-card link to the group detail page. The card itself handles
 *  navigation (role="link" + keyboard), so the team links inside the table can
 *  stay real <a>s without nesting <a> in <a>; those links stop propagation so a
 *  team click goes to the team, not the group. */
export function GroupCard({ group, index = 0 }: { group: Group; index?: number }) {
  const router = useRouter();
  const href = `/groups/${group.id}`;
  const go = () => router.push(href);

  return (
    <div
      role="link"
      tabIndex={0}
      aria-label={`${group.name} — view matches and standings`}
      onClick={go}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          go();
        }
      }}
      style={{ animationDelay: `${Math.min(index * 40, 400)}ms` }}
      className="glass card-hover fade-up group cursor-pointer rounded-2xl p-4 focus:outline-none focus-visible:ring-2 focus-visible:ring-win/50 sm:p-5"
    >
      <div className="mb-3 flex items-center justify-between gap-2">
        <span className="font-display text-lg font-bold tracking-tight">{group.name}</span>
        <span className="shrink-0 text-xs font-semibold text-muted transition group-hover:text-win">
          View matches <span aria-hidden>→</span>
        </span>
      </div>
      <GroupTable standings={group.standings} />
    </div>
  );
}
