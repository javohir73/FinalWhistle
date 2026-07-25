import { COMPETITIONS, type CompetitionId } from "@/lib/sports";
import { cn } from "@/lib/utils";

/**
 * Self-hosted competition identity. A fixed transparent canvas keeps every
 * mark aligned without introducing a white tile around the artwork.
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
  return (
    <span
      data-competition-logo={competition}
      className={cn("grid shrink-0 place-items-center", className)}
      style={{ width: size, height: size }}
    >
      {/* The assets are deliberately self-hosted: the prototype's remote logo
          URLs are vulnerable to CSP and hotlink blocking. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={config.logoSrc}
        alt={labelled ? `${config.label} logo` : ""}
        aria-hidden={labelled ? undefined : true}
        width={size}
        height={size}
        loading="lazy"
        decoding="async"
        className="h-full w-full object-contain p-[4%] drop-shadow-[0_1px_1px_rgba(0,0,0,0.45)]"
      />
    </span>
  );
}
