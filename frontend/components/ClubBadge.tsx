import { cn } from "@/lib/utils";

interface ClubIdentity {
  code: string;
  color: string;
  logoSrc: string;
}

/** Self-hosted club identities used by every active domestic-league dataset.
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

  Barcelona: { code: "BAR", color: "#004d98", logoSrc: "/clubs/laliga/barcelona.png" },
  "Atletico Madrid": { code: "ATM", color: "#cb3524", logoSrc: "/clubs/laliga/atletico-madrid.png" },
  "Athletic Club": { code: "BIL", color: "#ee2523", logoSrc: "/clubs/laliga/athletic-club.png" },
  Valencia: { code: "VAL", color: "#f9a01b", logoSrc: "/clubs/laliga/valencia.png" },
  Villarreal: { code: "VIL", color: "#f7df1e", logoSrc: "/clubs/laliga/villarreal.png" },
  Malaga: { code: "MAL", color: "#0092cf", logoSrc: "/clubs/laliga/malaga.png" },
  Sevilla: { code: "SEV", color: "#d71920", logoSrc: "/clubs/laliga/sevilla.png" },
  "Celta Vigo": { code: "CEL", color: "#8ac3ee", logoSrc: "/clubs/laliga/celta-vigo.png" },
  Levante: { code: "LEV", color: "#00529f", logoSrc: "/clubs/laliga/levante.png" },
  Espanyol: { code: "ESP", color: "#007fc8", logoSrc: "/clubs/laliga/espanyol.png" },
  "Real Madrid": { code: "RMA", color: "#febd11", logoSrc: "/clubs/laliga/real-madrid.png" },
  Alaves: { code: "ALA", color: "#005cab", logoSrc: "/clubs/laliga/alaves.png" },
  "Real Betis": { code: "BET", color: "#00954c", logoSrc: "/clubs/laliga/real-betis.png" },
  "Deportivo La Coruna": { code: "DEP", color: "#005ca9", logoSrc: "/clubs/laliga/deportivo-la-coruna.png" },
  Getafe: { code: "GET", color: "#005999", logoSrc: "/clubs/laliga/getafe.png" },
  "Real Sociedad": { code: "RSO", color: "#0067b1", logoSrc: "/clubs/laliga/real-sociedad.png" },
  Osasuna: { code: "OSA", color: "#d91a2a", logoSrc: "/clubs/laliga/osasuna.png" },
  "Rayo Vallecano": { code: "RAY", color: "#e30613", logoSrc: "/clubs/laliga/rayo-vallecano.png" },
  Elche: { code: "ELC", color: "#007a3d", logoSrc: "/clubs/laliga/elche.png" },
  "Racing Santander": { code: "RAC", color: "#008b4c", logoSrc: "/clubs/laliga/racing-santander.png" },

  "Bayern München": { code: "FCB", color: "#dc052d", logoSrc: "/clubs/bundesliga/bayern-munchen.png" },
  "SC Freiburg": { code: "SCF", color: "#e2001a", logoSrc: "/clubs/bundesliga/sc-freiburg.png" },
  "Werder Bremen": { code: "SVW", color: "#1d9053", logoSrc: "/clubs/bundesliga/werder-bremen.png" },
  "Borussia Mönchengladbach": { code: "BMG", color: "#111111", logoSrc: "/clubs/bundesliga/borussia-monchengladbach.png" },
  "FSV Mainz 05": { code: "M05", color: "#c3142d", logoSrc: "/clubs/bundesliga/fsv-mainz-05.png" },
  "Borussia Dortmund": { code: "BVB", color: "#fde100", logoSrc: "/clubs/bundesliga/borussia-dortmund.png" },
  "1899 Hoffenheim": { code: "TSG", color: "#1961a9", logoSrc: "/clubs/bundesliga/1899-hoffenheim.png" },
  "Bayer Leverkusen": { code: "B04", color: "#e32221", logoSrc: "/clubs/bundesliga/bayer-leverkusen.png" },
  "Eintracht Frankfurt": { code: "SGE", color: "#e1000f", logoSrc: "/clubs/bundesliga/eintracht-frankfurt.png" },
  "FC Augsburg": { code: "FCA", color: "#ba3733", logoSrc: "/clubs/bundesliga/fc-augsburg.png" },
  "VfB Stuttgart": { code: "VFB", color: "#e32219", logoSrc: "/clubs/bundesliga/vfb-stuttgart.png" },
  "RB Leipzig": { code: "RBL", color: "#dd0741", logoSrc: "/clubs/bundesliga/rb-leipzig.png" },
  "FC Schalke 04": { code: "S04", color: "#004d9d", logoSrc: "/clubs/bundesliga/fc-schalke-04.png" },
  "Hamburger SV": { code: "HSV", color: "#005aaa", logoSrc: "/clubs/bundesliga/hamburger-sv.png" },
  "Union Berlin": { code: "FCU", color: "#eb1923", logoSrc: "/clubs/bundesliga/union-berlin.png" },
  "SC Paderborn 07": { code: "SCP", color: "#005ca9", logoSrc: "/clubs/bundesliga/sc-paderborn-07.png" },
  "1. FC Köln": { code: "KOE", color: "#ed1c24", logoSrc: "/clubs/bundesliga/1-fc-koln.png" },
  "SV Elversberg": { code: "SVE", color: "#111111", logoSrc: "/clubs/bundesliga/sv-elversberg.png" },
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
  "FC Barcelona": "Barcelona",
  "Atlético Madrid": "Atletico Madrid",
  "Athletic Bilbao": "Athletic Club",
  "Deportivo La Coruña": "Deportivo La Coruna",
  "Bayern Munich": "Bayern München",
  "Borussia Monchengladbach": "Borussia Mönchengladbach",
  "FC Koln": "1. FC Köln",
  Hoffenheim: "1899 Hoffenheim",
  "Mainz 05": "FSV Mainz 05",
  "Schalke 04": "FC Schalke 04",
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
    // The source artwork spans everything from square shields to very tall
    // crests. Give every asset the same explicit square image box so intrinsic
    // aspect ratios cannot make narrow logos overflow their badge shell.
    const imageSize = size * 0.86;
    return (
      <span
        aria-hidden="true"
        data-club-logo={name ?? undefined}
        className={cn("grid shrink-0 place-items-center", className)}
        style={{ width: size, height: size }}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={club.logoSrc}
          alt=""
          width={size}
          height={size}
          loading="lazy"
          decoding="async"
          className="block object-contain drop-shadow-[0_1px_1px_rgba(0,0,0,0.5)]"
          style={{ width: imageSize, height: imageSize }}
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
