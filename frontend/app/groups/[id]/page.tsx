import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getGroupServer } from "@/lib/api";
import { APP_NAME } from "@/lib/constants";
import { GroupTable } from "@/components/GroupTable";

export async function generateMetadata({
  params,
}: {
  params: { id: string };
}): Promise<Metadata> {
  const group = await getGroupServer(params.id);
  if (!group) return { title: `Group — ${APP_NAME}` };
  const teams = group.standings.map((s) => s.team).join(", ");
  const title = `${group.name} — projected table | ${APP_NAME}`;
  const description = `${group.name} World Cup 2026 projected standings and qualification odds: ${teams}.`;
  return { title, description, openGraph: { title, description } };
}

export default async function GroupDetailPage({ params }: { params: { id: string } }) {
  const group = await getGroupServer(params.id);
  if (!group) notFound();

  return (
    <div className="fade-up mx-auto max-w-2xl">
      <Link href="/groups" className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-foreground">
        <span aria-hidden>←</span> All groups
      </Link>
      <h1 className="mb-5 mt-3 font-display text-3xl font-extrabold tracking-tight">
        {group.name}
      </h1>
      <div className="glass rounded-2xl p-6">
        <GroupTable standings={group.standings} />
      </div>
      <p className="mt-4 text-xs leading-relaxed text-muted">
        Points and goal difference are simulated averages over thousands of runs.
        Top two advance directly; the eight best third-placed teams also progress
        (see the Brackets page for the full knockout simulation).
      </p>
    </div>
  );
}
