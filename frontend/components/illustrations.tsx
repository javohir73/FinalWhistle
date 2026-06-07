/** Lightweight inline SVG football illustrations (no external assets). */

export function SoccerBall({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 100 100" className={className} aria-hidden>
      <circle cx="50" cy="50" r="46" fill="#f4f7f4" stroke="#0d130f" strokeWidth="2" />
      {/* center pentagon */}
      <path d="M50 30 L66 42 L60 61 L40 61 L34 42 Z" fill="#0d130f" />
      {/* outer partial pentagons */}
      <path d="M50 8 L62 16 L50 30 L38 16 Z" fill="#0d130f" />
      <path d="M92 44 L86 62 L66 42 L72 24 Z" fill="#0d130f" />
      <path d="M76 86 L58 84 L60 61 L80 66 Z" fill="#0d130f" />
      <path d="M24 86 L20 66 L40 61 L42 84 Z" fill="#0d130f" />
      <path d="M8 44 L28 24 L34 42 L14 62 Z" fill="#0d130f" />
      {/* seams */}
      <g stroke="#0d130f" strokeWidth="1.4" fill="none">
        <path d="M50 30 L50 16 M66 42 L86 44 M60 61 L72 78 M40 61 L28 78 M34 42 L14 44" />
      </g>
    </svg>
  );
}

/** Top-down pitch markings — used as a faint atmospheric backdrop. */
export function PitchLines({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 400 260" className={className} aria-hidden fill="none"
      stroke="hsl(var(--win))" strokeWidth="1.5" opacity="0.5">
      <rect x="6" y="6" width="388" height="248" rx="4" />
      <line x1="200" y1="6" x2="200" y2="254" />
      <circle cx="200" cy="130" r="46" />
      <circle cx="200" cy="130" r="3" fill="hsl(var(--win))" />
      {/* left box */}
      <rect x="6" y="70" width="58" height="120" />
      <rect x="6" y="104" width="24" height="52" />
      {/* right box */}
      <rect x="336" y="70" width="58" height="120" />
      <rect x="370" y="104" width="24" height="52" />
    </svg>
  );
}

/** Simple footballer silhouette built from primitives (reliable, scalable). */
export function Player({
  className,
  variant = "run",
}: {
  className?: string;
  variant?: "run" | "kick";
}) {
  const fill = "currentColor";
  return (
    <svg viewBox="0 0 80 120" className={className} aria-hidden>
      <g fill={fill}>
        {/* head */}
        <circle cx="42" cy="14" r="9" />
        {/* torso */}
        <path d="M34 24 q8 -3 14 2 l-3 34 q-9 3 -16 -2 z" />
        {variant === "run" ? (
          <>
            {/* arms */}
            <path d="M35 28 q-12 6 -16 18 l5 3 q6 -10 14 -14 z" />
            <path d="M47 27 q12 2 16 14 l-5 3 q-5 -9 -14 -11 z" />
            {/* legs (stride) */}
            <path d="M33 56 q-2 16 -12 26 l6 5 q12 -12 14 -28 z" />
            <path d="M44 58 q6 14 4 30 l-7 1 q0 -16 -6 -29 z" />
          </>
        ) : (
          <>
            {/* arms out for balance */}
            <path d="M35 28 q-14 2 -18 -6 l3 -5 q9 5 17 4 z" />
            <path d="M47 27 q12 4 14 14 l-5 3 q-3 -8 -12 -11 z" />
            {/* planted + kicking leg */}
            <path d="M34 56 q-3 16 -2 32 l7 0 q0 -16 3 -31 z" />
            <path d="M44 57 q12 6 22 4 l-1 7 q-13 1 -25 -6 z" />
          </>
        )}
      </g>
    </svg>
  );
}
