import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getGroupServer, getUpcomingMatchesServer } from "@/lib/api";
import { APP_NAME } from "@/lib/constants";
import { GroupTable } from "@/components/GroupTable";
import { GroupFixtureList } from "@/components/GroupFixtureList";

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
  const [group, allMatches] = await Promise.all([
    getGroupServer(params.id),
    getUpcomingMatchesServer(),
  ]);
  if (!group) notFound();

  const fixtures = (allMatches ?? [])
    .filter((m) => m.group === group.name)
    .sort((a, b) => {
      if (!a.kickoff_utc) return 1;
      if (!b.kickoff_utc) return -1;
      return a.kickoff_utc < b.kickoff_utc ? -1 : 1;
    });

  return (
    <div className="fade-up mx-auto max-w-3xl space-y-6">
      <Link href="/groups" className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-foreground">
        <span aria-hidden>←</span> All groups
      </Link>
      <h1 className="mt-3 font-display text-3xl font-extrabold tracking-tight">
        {group.name}
      </h1>

      {/* Projected table + qualification odds */}
      <section className="glass rounded-2xl p-6">
        <h2 className="mb-4 font-display text-lg font-bold">Projected standings</h2>
        <GroupTable standings={group.standings} />
        <p className="mt-4 text-xs leading-relaxed text-muted">
          Points and goal difference are simulated averages over thousands of runs;
          &ldquo;Qualify&rdquo; is each team&apos;s chance of reaching the knockouts.
          Top two advance directly; the eight best third-placed teams also progress.
        </p>
      </section>

      {/* All group fixtures */}
      <section>
        <h2 className="mb-3 font-display text-lg font-bold">{group.name} fixtures</h2>
        <GroupFixtureList matches={fixtures} />
      </section>

      {/* Explore */}
      <section>
        <h2 className="mb-3 font-display text-xs font-bold uppercase tracking-[0.2em] text-muted">
          Explore
        </h2>
        <div className="grid gap-3 sm:grid-cols-2">
          <ExploreLink href="/brackets" label="Tournament odds" sub="Qualification, title & round-by-round" />
          <ExploreLink href="/matches" label="All matches" sub="Every fixture across the groups" />
        </div>
      </section>
    </div>
  );
}

function ExploreLink({ href, label, sub }: { href: string; label: string; sub: string }) {
  return (
    <Link
      href={href}
      className="card-hover glass flex items-center justify-between gap-2 rounded-xl px-4 py-3 focus:outline-none focus-visible:ring-2 focus-visible:ring-win/50"
    >
      <span className="min-w-0">
        <span className="block truncate font-display text-sm font-bold">{label}</span>
        <span className="block truncate text-xs text-muted">{sub}</span>
      </span>
      <span className="shrink-0 text-win" aria-hidden>→</span>
    </Link>
  );
}
