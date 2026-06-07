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
    <div className="fade-up mx-auto max-w-2xl">
      <Link href="/groups" className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-foreground">
        <span aria-hidden>←</span> All groups
      </Link>
      <h1 className="mb-5 mt-3 font-display text-3xl font-extrabold tracking-tight">
        {state.data.name}
      </h1>
      <div className="glass rounded-2xl p-6">
        <GroupTable standings={state.data.standings} />
      </div>
      <p className="mt-4 text-xs leading-relaxed text-muted/70">
        Points and goal difference are simulated averages over thousands of runs.
        Top two advance directly; the eight best third-placed teams also progress
        (modeled in a later release).
      </p>
    </div>
  );
}
