import { COMPETITIONS, type CompetitionId } from "@/lib/sports";
import { cn } from "@/lib/utils";

/**
 * Self-hosted competition identity. The logo sits on a pale disc so dark marks
 * remain legible on Floodlight's pitch canvas. Callers normally keep it
 * decorative because the competition name is printed alongside it.
 */
export function CompetitionLogo({
  competition,
  size = 28,
  className,
  labelled = false,
}: {
  competition: CompetitionId;
  size?: number;
  className?: string;
  labelled?: boolean;
}) {
  const config = COMPETITIONS[competition];
  const inset = Math.max(2, Math.round(size * 0.14));

  return (
    <span
      className={cn(
        "grid shrink-0 place-items-center overflow-hidden rounded-full bg-white/95 ring-1 ring-border/80",
        className,
      )}
      style={{ width: size, height: size }}
    >
      {/* The assets are deliberately self-hosted: the prototype's remote logo
          URLs are vulnerable to CSP and hotlink blocking. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={config.logoSrc}
        alt={labelled ? `${config.label} logo` : ""}
        aria-hidden={labelled ? undefined : true}
        width={size - inset * 2}
        height={size - inset * 2}
        loading="lazy"
        decoding="async"
        className="h-auto max-h-full w-auto max-w-full object-contain"
      />
    </span>
  );
}
