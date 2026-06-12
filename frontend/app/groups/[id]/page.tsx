import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getGroupServer, getUpcomingMatchesServer } from "@/lib/api";
import { APP_NAME } from "@/lib/constants";
import { GroupTable } from "@/components/GroupTable";
import { GroupFixtureList } from "@/components/GroupFixtureList";
import { ShareButton } from "@/components/ShareButton";

export async function generateMetadata({
  params,
}: {
  params: { id: string };
}): Promise<Metadata> {
  const group = await getGroupServer(params.id);
  if (!group) return { title: `Group — ${APP_NAME}` };
  const teams = group.standings.map((s) => s.team).join(", ");
  const title = `${group.name} — standings & qualification odds | ${APP_NAME}`;
  const description = `${group.name} World Cup 2026 live standings and qualification odds: ${teams}.`;
  return {
    title, description,
    alternates: { canonical: `/groups/${params.id}` },
    openGraph: { title, description },
  };
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
      <div className="flex items-center justify-between gap-3">
        <Link href="/groups" className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-foreground">
          <span aria-hidden>←</span> All groups
        </Link>
        <ShareButton title={`${group.name} — World Cup 2026 standings`} />
      </div>
      <h1 className="mt-3 font-display text-3xl font-extrabold tracking-tight">
        {group.name}
      </h1>

      {/* Live table + qualification odds */}
      <section className="glass rounded-2xl p-6">
        <h2 className="mb-4 font-display text-lg font-bold">Standings</h2>
        <GroupTable standings={group.standings} />
        <p className="mt-4 text-xs leading-relaxed text-muted">
          Points and goal difference come from real results — a live match&apos;s current
          score counts provisionally. &ldquo;Top 2&rdquo; is the model&apos;s chance of each
          team finishing in the top two — i.e. direct qualification. (The eight best
          third-placed teams also reach the Round of 32; those odds aren&apos;t shown in
          this column.)
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
