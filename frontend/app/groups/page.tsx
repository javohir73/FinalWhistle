"use client";

import Link from "next/link";
import { getGroups } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { GroupTable } from "@/components/GroupTable";
import { ErrorState, Empty } from "@/components/States";

export default function GroupsPage() {
  const state = useFetch(getGroups, []);

  return (
    <div>
      <header className="fade-up mb-8">
        <h1 className="font-display text-3xl font-extrabold tracking-tight sm:text-4xl">
          Group standings
        </h1>
        <p className="mt-2 max-w-xl text-muted">
          Predicted final tables from thousands of Monte-Carlo simulations. The top
          two of each group (highlighted) advance directly.
        </p>
      </header>

      {state.status === "loading" && (
        <div className="grid gap-5 md:grid-cols-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="glass rounded-2xl p-5">
              <div className="skeleton mb-4 h-5 w-24 rounded" />
              {Array.from({ length: 4 }).map((_, j) => (
                <div key={j} className="skeleton mb-2 h-8 w-full rounded" />
              ))}
            </div>
          ))}
        </div>
      )}
      {state.status === "error" && <ErrorState message={state.message} />}
      {state.status === "success" &&
        (state.data.length === 0 ? (
          <Empty />
        ) : (
          <div className="grid gap-5 md:grid-cols-2">
            {state.data.map((g, i) => (
              <div
                key={g.id}
                className="glass card-hover fade-up rounded-2xl p-5"
                style={{ animationDelay: `${Math.min(i * 40, 400)}ms` }}
              >
                <Link
                  href={`/groups/${g.id}`}
                  className="mb-3 inline-block font-display text-lg font-bold tracking-tight hover:text-win"
                >
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
