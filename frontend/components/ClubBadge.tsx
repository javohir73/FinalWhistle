import { cn } from "@/lib/utils";

interface ClubIdentity {
  code: string;
  color: string;
  logoSrc: string;
}

/** Self-hosted club identities used by the current NRL and EPL datasets.
 *  Unknown/future clubs still degrade to the previous colored monogram. */
const CLUBS: Record<string, ClubIdentity> = {
  Broncos: { code: "BRI", color: "#6b1d45", logoSrc: "/clubs/nrl/broncos.svg" },
  Raiders: { code: "CBR", color: "#95c11f", logoSrc: "/clubs/nrl/raiders.svg" },
  Bulldogs: { code: "CBY", color: "#00539f", logoSrc: "/clubs/nrl/bulldogs.svg" },
  Sharks: { code: "CRO", color: "#00a9d8", logoSrc: "/clubs/nrl/sharks.svg" },
  Dolphins: { code: "DOL", color: "#c41e3a", logoSrc: "/clubs/nrl/dolphins.svg" },
  Titans: { code: "GLD", color: "#009fd9", logoSrc: "/clubs/nrl/titans.svg" },
  "Sea Eagles": { code: "MAN", color: "#7d0025", logoSrc: "/clubs/nrl/sea-eagles.svg" },
  Storm: { code: "MEL", color: "#4f2683", logoSrc: "/clubs/nrl/storm.svg" },
  Knights: { code: "NEW", color: "#003b73", logoSrc: "/clubs/nrl/knights.svg" },
  Cowboys: { code: "NQL", color: "#002d61", logoSrc: "/clubs/nrl/cowboys.svg" },
  Eels: { code: "PAR", color: "#006eb5", logoSrc: "/clubs/nrl/eels.svg" },
  Panthers: { code: "PEN", color: "#17181a", logoSrc: "/clubs/nrl/panthers.svg" },
  Rabbitohs: { code: "SOU", color: "#0d5442", logoSrc: "/clubs/nrl/rabbitohs.svg" },
  Dragons: { code: "SGI", color: "#e02627", logoSrc: "/clubs/nrl/dragons.svg" },
  Roosters: { code: "SYD", color: "#002b5c", logoSrc: "/clubs/nrl/roosters.svg" },
  Warriors: { code: "WAR", color: "#151f6d", logoSrc: "/clubs/nrl/warriors.svg" },
  "Wests Tigers": { code: "WST", color: "#f68b1f", logoSrc: "/clubs/nrl/wests-tigers.svg" },

  Arsenal: { code: "ARS", color: "#ef0107", logoSrc: "/clubs/epl/arsenal.png" },
  "Aston Villa": { code: "AVL", color: "#670e36", logoSrc: "/clubs/epl/aston-villa.png" },
  Bournemouth: { code: "BOU", color: "#da291c", logoSrc: "/clubs/epl/bournemouth.png" },
  Brentford: { code: "BRE", color: "#e30613", logoSrc: "/clubs/epl/brentford.png" },
  Brighton: { code: "BHA", color: "#0057b8", logoSrc: "/clubs/epl/brighton.png" },
  Chelsea: { code: "CHE", color: "#034694", logoSrc: "/clubs/epl/chelsea.png" },
  "Crystal Palace": { code: "CRY", color: "#1b458f", logoSrc: "/clubs/epl/crystal-palace.png" },
  Coventry: { code: "COV", color: "#69b3e7", logoSrc: "/clubs/epl/coventry.png" },
  Everton: { code: "EVE", color: "#003399", logoSrc: "/clubs/epl/everton.png" },
  Fulham: { code: "FUL", color: "#111111", logoSrc: "/clubs/epl/fulham.png" },
  "Hull City": { code: "HUL", color: "#f5a12d", logoSrc: "/clubs/epl/hull-city.png" },
  Ipswich: { code: "IPS", color: "#0044aa", logoSrc: "/clubs/epl/ipswich.png" },
  Leeds: { code: "LEE", color: "#ffcd00", logoSrc: "/clubs/epl/leeds.png" },
  Liverpool: { code: "LIV", color: "#c8102e", logoSrc: "/clubs/epl/liverpool.png" },
  "Manchester City": { code: "MCI", color: "#6cabdd", logoSrc: "/clubs/epl/manchester-city.png" },
  "Manchester United": { code: "MUN", color: "#da291c", logoSrc: "/clubs/epl/manchester-united.png" },
  Newcastle: { code: "NEW", color: "#241f20", logoSrc: "/clubs/epl/newcastle.png" },
  "Nottingham Forest": { code: "NFO", color: "#dd0000", logoSrc: "/clubs/epl/nottingham-forest.png" },
  Sunderland: { code: "SUN", color: "#eb172b", logoSrc: "/clubs/epl/sunderland.png" },
  Tottenham: { code: "TOT", color: "#132257", logoSrc: "/clubs/epl/tottenham.png" },
};

const CLUB_ALIASES: Record<string, string> = {
  "Brisbane Broncos": "Broncos",
  "Canberra Raiders": "Raiders",
  "Canterbury Bulldogs": "Bulldogs",
  "Canterbury-Bankstown Bulldogs": "Bulldogs",
  "Cronulla Sharks": "Sharks",
  "Cronulla-Sutherland Sharks": "Sharks",
  "Gold Coast Titans": "Titans",
  "Manly Sea Eagles": "Sea Eagles",
  "Manly-Warringah Sea Eagles": "Sea Eagles",
  "Melbourne Storm": "Storm",
  "Newcastle Knights": "Knights",
  "North Queensland Cowboys": "Cowboys",
  "Parramatta Eels": "Eels",
  "Penrith Panthers": "Panthers",
  "South Sydney Rabbitohs": "Rabbitohs",
  "St George Illawarra Dragons": "Dragons",
  "Sydney Roosters": "Roosters",
  "New Zealand Warriors": "Warriors",
  "AFC Bournemouth": "Bournemouth",
  "Brighton & Hove Albion": "Brighton",
  "Coventry City": "Coventry",
  "Hull City AFC": "Hull City",
  "Ipswich Town": "Ipswich",
  "Leeds United": "Leeds",
  "Man City": "Manchester City",
  "Man Utd": "Manchester United",
  "Newcastle United": "Newcastle",
  "Nottingham Forest FC": "Nottingham Forest",
  Spurs: "Tottenham",
  "Tottenham Hotspur": "Tottenham",
};

export function ClubBadge({
  name,
  size = 24,
  className,
}: {
  name: string | null;
  size?: number;
  className?: string;
}) {
  const canonicalName = name ? (CLUB_ALIASES[name] ?? name) : null;
  const club = canonicalName ? CLUBS[canonicalName] : undefined;
  const code = club?.code ?? (name ?? "?").slice(0, 3).toUpperCase();

  if (club) {
    const inset = Math.max(2, Math.round(size * 0.1));
    return (
      <span
        aria-hidden="true"
        data-club-logo={name ?? undefined}
        className={cn(
          "grid shrink-0 place-items-center overflow-hidden rounded-lg bg-white/95 ring-1 ring-border/80",
          className,
        )}
        style={{ width: size, height: size }}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={club.logoSrc}
          alt=""
          width={size - inset * 2}
          height={size - inset * 2}
          loading="lazy"
          decoding="async"
          className="h-auto max-h-full w-auto max-w-full object-contain"
        />
      </span>
    );
  }

  return (
    <span
      aria-hidden="true"
      className={cn(
        "grid shrink-0 place-items-center rounded-lg font-display font-bold text-white",
        className,
      )}
      style={{
        width: size,
        height: size,
        fontSize: size * 0.34,
        backgroundColor: "hsl(var(--pitch))",
      }}
    >
      {code}
    </span>
  );
}
