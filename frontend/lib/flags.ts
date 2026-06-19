/** Map WC2026 team names -> ISO 3166-1 alpha-2 codes for flag images.
 *  Flags are served from flagcdn.com (free, no key). gb-eng / gb-sct are the
 *  flagcdn codes for England / Scotland. */
const NAME_TO_ISO2: Record<string, string> = {
  Mexico: "mx",
  "South Africa": "za",
  "South Korea": "kr",
  Czechia: "cz",
  Canada: "ca",
  "Bosnia and Herzegovina": "ba",
  Qatar: "qa",
  Switzerland: "ch",
  Brazil: "br",
  Morocco: "ma",
  Haiti: "ht",
  Scotland: "gb-sct",
  "United States": "us",
  Paraguay: "py",
  Australia: "au",
  Turkey: "tr",
  Germany: "de",
  "Curaçao": "cw",
  "Ivory Coast": "ci",
  Ecuador: "ec",
  Netherlands: "nl",
  Japan: "jp",
  Sweden: "se",
  Tunisia: "tn",
  Belgium: "be",
  Egypt: "eg",
  Iran: "ir",
  "New Zealand": "nz",
  Spain: "es",
  "Cape Verde": "cv",
  "Saudi Arabia": "sa",
  Uruguay: "uy",
  France: "fr",
  Senegal: "sn",
  Iraq: "iq",
  Norway: "no",
  Argentina: "ar",
  Algeria: "dz",
  Austria: "at",
  Jordan: "jo",
  Portugal: "pt",
  "DR Congo": "cd",
  Uzbekistan: "uz",
  Colombia: "co",
  England: "gb-eng",
  Croatia: "hr",
  Ghana: "gh",
  Panama: "pa",
};

/** Self-hosted flag for the in-app flag chips. The PNGs live in
 *  `public/flags/<iso>.png` (flagcdn w320, ~0.2–5 KB each, ~200 KB total) so
 *  they render crisp on retina at every chip size (≤88px → ≥3× headroom) and
 *  load fast from our own origin instead of firing ~48 requests at a free CDN. */
export function localFlag(teamName: string): string | null {
  const iso = NAME_TO_ISO2[teamName];
  return iso ? `/flags/${iso}.png` : null;
}

/** Absolute flagcdn URL. Used only by the server-rendered OG-image routes, whose
 *  image renderer needs an absolute URL (a relative `/flags/...` path won't
 *  resolve there). In-app chips use `localFlag` above. */
export function flagUrl(teamName: string, width: 40 | 80 | 160 | 320 = 80): string | null {
  const iso = NAME_TO_ISO2[teamName];
  return iso ? `https://flagcdn.com/w${width}/${iso}.png` : null;
}

/** Two-letter initials fallback when no flag is available. */
export function teamInitials(teamName: string): string {
  return teamName
    .split(/\s+/)
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}
