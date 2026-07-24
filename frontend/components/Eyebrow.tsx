import { COMPETITIONS, type CompetitionId } from "@/lib/sports";
import { cn } from "@/lib/utils";

interface EyebrowProps {
  children: React.ReactNode;
  tone?: "lime" | "muted";
}

/** Uppercase tracked label above a section (prototype:
 *  `font:700 11px 'Hanken Grotesk';letter-spacing:.16em`). Hanken is the body
 *  default, so no font-display class. 11px is the a11y floor for labels --
 *  never go smaller. */
export function Eyebrow({ children, tone = "lime" }: EyebrowProps) {
  return (
    <p
      className={cn(
        "text-[11px] font-semibold uppercase tracking-[0.16em]",
        tone === "lime" ? "text-lime-deep" : "text-muted",
      )}
    >
      {children}
    </p>
  );
}

/** League accent pill (plan §2): the per-competition accent color, used ONLY
 *  here and on the switcher overlay, at <=12% opacity -- lime stays the sole
 *  action color. Same idiom as CompetitionOverlay's accent pill. */
export function CompEyebrowChip({ comp }: { comp: CompetitionId }) {
  const competition = COMPETITIONS[comp];
  return (
    <span
      className="rounded-full px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide"
      style={{
        backgroundColor: `hsl(var(${competition.accentVar}) / 0.12)`,
        color: `hsl(var(${competition.accentVar}))`,
      }}
    >
      {competition.shortLabel}
    </span>
  );
}
