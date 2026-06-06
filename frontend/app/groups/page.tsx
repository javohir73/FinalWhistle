"use client";

import Link from "next/link";
import { getGroups } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { GroupTable } from "@/components/GroupTable";
import { Loading, ErrorState, Empty } from "@/components/States";

export default function GroupsPage() {
  const state = useFetch(getGroups, []);

  return (
    <div>
      <h1 className="mb-1 text-2xl font-bold">Group standings</h1>
      <p className="mb-6 text-foreground/60">
        Predicted final tables and qualification probabilities. Top two (highlighted)
        advance directly.
      </p>

      {state.status === "loading" && <Loading label="Loading groups…" />}
      {state.status === "error" && <ErrorState message={state.message} />}
      {state.status === "success" &&
        (state.data.length === 0 ? (
          <Empty />
        ) : (
          <div className="grid gap-5 md:grid-cols-2">
            {state.data.map((g) => (
              <div key={g.id} className="rounded-xl border border-border p-4">
                <Link href={`/groups/${g.id}`} className="mb-2 inline-block font-semibold hover:underline">
                  {g.name}
                </Link>
                <GroupTable standings={g.standings} />
              </div>
            ))}
          </div>
        ))}
    </div>
  );
}
