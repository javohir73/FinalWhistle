import { cn } from "@/lib/utils";

const ICONS: Record<string, React.ReactNode> = {
  Home: <path d="M3 11l9-8 9 8M5 10v10h14V10" strokeLinejoin="round" strokeLinecap="round" />,
  Matches: (
    <>
      <rect x="3" y="5" width="18" height="16" rx="3" />
      <path d="M8 3v4M16 3v4M3 10h18" strokeLinecap="round" />
    </>
  ),
  Fixtures: (
    <>
      <rect x="3" y="5" width="18" height="16" rx="3" />
      <path d="M8 3v4M16 3v4M3 10h18" strokeLinecap="round" />
    </>
  ),
  Groups: (
    <>
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
    </>
  ),
  Bracket: <path d="M4 5h6v6M4 19h6v-6M10 8h5v8h-5M15 12h5" strokeLinejoin="round" strokeLinecap="round" />,
  Ladder: <path d="M4 6h16M4 12h16M4 18h10" strokeLinecap="round" />,
  Standings: <path d="M4 6h16M4 12h16M4 18h10" strokeLinecap="round" />,
  Record: <path d="M4 19l6-7 4 3 6-8" strokeLinejoin="round" strokeLinecap="round" />,
  Football: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path
        d="m12 7 3.3 2.4-1.2 3.9H9.9L8.7 9.4 12 7Zm-3.3 2.4L5.5 8m3.2 1.4-2.1 5.1m3.3-1.2-1 4.8m5.2-4.8 1 4.8m.2-8.7L18.5 8m-1.1 6.5 2.1 1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </>
  ),
  NRL: (
    <>
      <path d="M5 4h14v7c0 4.6-2.8 7.8-7 10-4.2-2.2-7-5.4-7-10V4Z" strokeLinejoin="round" />
      <path d="M8 9h8M9 13h6" strokeLinecap="round" />
    </>
  ),
  You: (
    <>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21c0-4 4-6 8-6s8 2 8 6" strokeLinecap="round" />
    </>
  ),
  Tips: (
    <>
      <path d="M9 3h6a1 1 0 011 1v1H8V4a1 1 0 011-1Z" strokeLinejoin="round" />
      <rect x="5" y="5" width="14" height="16" rx="2" />
      <path d="M9 12.5l2 2 4-4.5" strokeLinecap="round" strokeLinejoin="round" />
    </>
  ),
  Play: (
    <>
      <path d="M9 3h6a1 1 0 011 1v1H8V4a1 1 0 011-1Z" strokeLinejoin="round" />
      <rect x="5" y="5" width="14" height="16" rx="2" />
      <path d="M9 12.5l2 2 4-4.5" strokeLinecap="round" strokeLinejoin="round" />
    </>
  ),
};

/** One icon vocabulary for desktop and mobile navigation. */
export function NavIcon({
  name,
  active = false,
  className,
}: {
  name: string;
  active?: boolean;
  className?: string;
}) {
  const glyph = ICONS[name];
  if (!glyph) return null;
  return (
    <svg
      viewBox="0 0 24 24"
      className={cn("shrink-0", className)}
      fill="none"
      stroke="currentColor"
      strokeWidth={active ? 2.4 : 2}
      aria-hidden="true"
    >
      {glyph}
    </svg>
  );
}
