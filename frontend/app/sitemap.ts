import type { MetadataRoute } from "next";

const SITE = "https://fifa-wc26-prediction.vercel.app";
const API = process.env.NEXT_PUBLIC_API_URL || "https://pitchprophet-api.onrender.com";

/** Fetch a list of ids from the API; never throws (sitemap must build even if
 *  the backend is briefly unreachable). ISR-revalidated hourly. */
async function ids<T>(path: string, pick: (row: T) => number): Promise<number[]> {
  try {
    const res = await fetch(`${API}${path}`, { next: { revalidate: 3600 } });
    if (!res.ok) return [];
    const data = (await res.json()) as T[];
    return data.map(pick).filter((n) => Number.isFinite(n));
  } catch {
    return [];
  }
}

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const [matchIds, teamIds, groupIds] = await Promise.all([
    ids<{ match_id: number }>("/api/matches/upcoming", (m) => m.match_id),
    ids<{ id: number }>("/api/teams", (t) => t.id),
    ids<{ id: number }>("/api/groups", (g) => g.id),
  ]);

  const staticRoutes: MetadataRoute.Sitemap = [
    { url: SITE, changeFrequency: "daily", priority: 1 },
    // Floodlight P1 slice p1-s3 301'd /matches, /groups, /brackets to their
    // /football/wc26/... equivalents (next.config.mjs) -- list the live URLs
    // here instead, or Googlebot only ever sees redirect targets from this
    // sitemap. /leaderboard is cross-competition and wasn't moved.
    ...["/football/wc26/fixtures", "/football/wc26/groups", "/football/wc26/bracket", "/leaderboard"].map((p) => ({
      url: `${SITE}${p}`,
      changeFrequency: "daily" as const,
      priority: 0.7,
    })),
    ...["/about", "/methodology"].map((p) => ({
      url: `${SITE}${p}`,
      changeFrequency: "monthly" as const,
      priority: 0.5,
    })),
  ];

  // Same 301 move applies to the per-id content pages -- point these at the
  // live /football/wc26/... paths (see the static-routes comment above).
  const dynamicRoutes: MetadataRoute.Sitemap = [
    ...matchIds.map((id) => ({
      url: `${SITE}/football/wc26/match/${id}`,
      changeFrequency: "daily" as const,
      priority: 0.6,
    })),
    ...groupIds.map((id) => ({
      url: `${SITE}/football/wc26/groups/${id}`,
      changeFrequency: "daily" as const,
      priority: 0.5,
    })),
    ...teamIds.map((id) => ({
      url: `${SITE}/football/wc26/team/${id}`,
      changeFrequency: "weekly" as const,
      priority: 0.5,
    })),
  ];

  return [...staticRoutes, ...dynamicRoutes];
}
