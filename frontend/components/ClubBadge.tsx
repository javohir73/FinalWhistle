/** NRL club monogram: 3-letter code on the club's primary color. Replaces the
 *  country <Flag/> in NRL cards. Unknown clubs fall back to initials on pitch. */
const CLUBS: Record<string, { code: string; color: string }> = {
  Broncos: { code: "BRI", color: "#6b1d45" },
  Raiders: { code: "CBR", color: "#95c11f" },
  Bulldogs: { code: "CBY", color: "#00539f" },
  Sharks: { code: "CRO", color: "#00a9d8" },
  Dolphins: { code: "DOL", color: "#c41e3a" },
  Titans: { code: "GLD", color: "#009fd9" },
  "Sea Eagles": { code: "MAN", color: "#7d0025" },
  Storm: { code: "MEL", color: "#4f2683" },
  Knights: { code: "NEW", color: "#003b73" },
  Cowboys: { code: "NQL", color: "#002d61" },
  Eels: { code: "PAR", color: "#006eb5" },
  Panthers: { code: "PEN", color: "#17181a" },
  Rabbitohs: { code: "SOU", color: "#0d5442" },
  Dragons: { code: "SGI", color: "#e02627" },
  Roosters: { code: "SYD", color: "#002b5c" },
  Warriors: { code: "WAR", color: "#151f6d" },
  "Wests Tigers": { code: "WST", color: "#f68b1f" },
};

export function ClubBadge({ name, size = 24 }: { name: string | null; size?: number }) {
  const club = name ? CLUBS[name] : undefined;
  const code = club?.code ?? (name ?? "?").slice(0, 3).toUpperCase();
  return (
    <span
      aria-hidden="true"
      className="grid shrink-0 place-items-center rounded-lg font-display font-bold text-white"
      style={{
        width: size,
        height: size,
        fontSize: size * 0.34,
        backgroundColor: club?.color ?? "hsl(var(--pitch))",
      }}
    >
      {code}
    </span>
  );
}
