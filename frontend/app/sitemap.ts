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
    ...["/matches", "/groups", "/brackets", "/leaderboard"].map((p) => ({
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

  const dynamicRoutes: MetadataRoute.Sitemap = [
    ...matchIds.map((id) => ({ url: `${SITE}/match/${id}`, changeFrequency: "daily" as const, priority: 0.6 })),
    ...groupIds.map((id) => ({ url: `${SITE}/groups/${id}`, changeFrequency: "daily" as const, priority: 0.5 })),
    ...teamIds.map((id) => ({ url: `${SITE}/team/${id}`, changeFrequency: "weekly" as const, priority: 0.5 })),
  ];

  return [...staticRoutes, ...dynamicRoutes];
}
