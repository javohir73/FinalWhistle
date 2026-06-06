"use client";

import Link from "next/link";
import { getGroup } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { GroupTable } from "@/components/GroupTable";
import { Loading, ErrorState } from "@/components/States";

export default function GroupDetailPage({ params }: { params: { id: string } }) {
  const { id } = params;
  const state = useFetch(() => getGroup(id), [id]);

  if (state.status === "loading") return <Loading label="Loading group…" />;
  if (state.status === "error") return <ErrorState message={state.message} />;

  return (
    <div>
      <Link href="/groups" className="text-sm text-foreground/60 hover:underline">
        ← All groups
      </Link>
      <h1 className="mb-4 mt-2 text-2xl font-bold">{state.data.name}</h1>
      <div className="rounded-xl border border-border p-4">
        <GroupTable standings={state.data.standings} />
      </div>
      <p className="mt-4 text-xs text-foreground/50">
        Points and goal difference are simulated averages over thousands of runs.
        Top two advance directly; the eight best third-placed teams also progress
        (modeled in a later release).
      </p>
    </div>
  );
}
