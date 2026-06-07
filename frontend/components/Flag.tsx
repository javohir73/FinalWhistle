import { flagUrl, teamInitials } from "@/lib/flags";
import { cn } from "@/lib/utils";

/** Rounded flag chip with a typographic fallback. Uses next/image-free <img>
 *  since flagcdn is a remote CDN and these are tiny. */
export function Flag({
  team,
  size = 28,
  className,
}: {
  team: string;
  size?: number;
  className?: string;
}) {
  const url = flagUrl(team);
  if (!url) {
    return (
      <span
        className={cn(
          "grid shrink-0 place-items-center rounded-full bg-surface-2 text-[10px] font-bold text-muted ring-1 ring-border",
          className,
        )}
        style={{ width: size, height: size }}
        aria-hidden
      >
        {teamInitials(team)}
      </span>
    );
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={url}
      alt=""
      aria-hidden
      width={size}
      height={size}
      loading="lazy"
      className={cn("shrink-0 rounded-full object-cover ring-1 ring-border/80", className)}
      style={{ width: size, height: size }}
    />
  );
}
