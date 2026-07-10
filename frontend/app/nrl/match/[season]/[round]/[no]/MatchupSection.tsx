"use client";

/** Wave 2 "matchup" intel section: attack/defence tier ranks for both clubs.
 *  Self-contained client island -- team names come straight off the Wave 1
 *  match detail already threaded through IntelSectionProps
 *  (`detail.match.home` / `detail.match.away`), then loads both
 *  /teams/{slug}/profile responses through the /backend-api rewrite. The
 *  only Wave 1 file this feature touches is sections.ts (one appended array
 *  entry) -- this file and its components are new, per the extension
 *  contract. */
import { useEffect, useState } from "react";
import { CLIENT_BASE } from "@/lib/api";
import { slugify } from "@/lib/nrlSlug";
import type { NrlStatsProfile } from "@/lib/types";
import type { IntelSectionProps } from "./sections";
import { MatchupTiers } from "@/components/nrl/MatchupTiers";

type Side = { name: string; profile: NrlStatsProfile | null };

export default function MatchupSection({ detail }: IntelSectionProps) {
  const homeName = detail.match.home;
  const awayName = detail.match.away;
  const [sides, setSides] = useState<{ home: Side; away: Side } | null | undefined>(undefined);

  useEffect(() => {
    if (!homeName || !awayName) {
      setSides(null);
      return;
    }
    let cancelled = false;

    // Belt-and-braces: guard each fetch call itself, not just the promise
    // chain, so an environment without a global `fetch` degrades to the
    // quiet placeholder rather than throwing out of the effect.
    function fetchProfile(name: string): Promise<NrlStatsProfile | null> {
      try {
        return fetch(`${CLIENT_BASE}/api/nrl/teams/${slugify(name)}/profile`, { cache: "no-store" })
          .then((res) => (res.ok ? res.json() : null))
          .catch(() => null);
      } catch {
        return Promise.resolve(null);
      }
    }

    Promise.all([fetchProfile(homeName), fetchProfile(awayName)]).then(([homeProfile, awayProfile]) => {
      if (!cancelled) {
        setSides({
          home: { name: homeName, profile: homeProfile },
          away: { name: awayName, profile: awayProfile },
        });
      }
    });

    return () => {
      cancelled = true;
    };
  }, [homeName, awayName]);

  if (sides === undefined) {
    return <div className="glass rounded-2xl p-6 text-sm text-muted">Loading matchup…</div>;
  }
  if (sides === null) {
    return (
      <div className="glass rounded-2xl p-6 text-sm text-muted">
        Matchup profiles are unavailable for this fixture.
      </div>
    );
  }
  return <MatchupTiers home={sides.home} away={sides.away} />;
}
