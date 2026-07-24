import type { StandingsZone } from "@/lib/sports";

/** First zone whose rank band [from, to] contains `rank`, else null. Pure and
 *  SSR-safe -- no React -- so StandingsTable (P2 slice p2-s4) can call it
 *  during render on either side. */
export function zoneForRank(zones: StandingsZone[], rank: number): StandingsZone | null {
  return zones.find((z) => rank >= z.from && rank <= z.to) ?? null;
}

/** Tailwind classes for a zone's `tone`. The component owns the actual hues
 *  (per StandingsZone's doc comment in lib/sports.ts): cl/promo/finals share
 *  the win (lime) treatment, europa gets gold, releg gets loss (rose), and
 *  none renders nothing. */
export function zoneToneClasses(
  tone: StandingsZone["tone"],
): { stripe: string; bg: string; rankText: string } {
  switch (tone) {
    case "cl":
    case "promo":
    case "finals":
      return { stripe: "border-l-win", bg: "bg-win/[0.04]", rankText: "text-lime-deep" };
    case "europa":
      return { stripe: "border-l-gold", bg: "bg-gold/[0.04]", rankText: "text-gold" };
    case "releg":
      return { stripe: "border-l-loss", bg: "bg-loss/[0.04]", rankText: "text-loss" };
    case "none":
      return { stripe: "", bg: "", rankText: "" };
  }
}
