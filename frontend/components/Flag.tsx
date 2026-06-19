"use client";

import { useState } from "react";
import { localFlag, teamInitials } from "@/lib/flags";
import { cn } from "@/lib/utils";

/** Rounded flag chip. Flags are self-hosted PNGs (`public/flags`, flagcdn w320,
 *  ~0.2–5 KB each) so they stay crisp on retina at every chip size and load fast
 *  from our own origin — no remote-CDN burst on the country chooser. If a flag is
 *  missing (unmapped team or a stray load error) we show a clean typographic chip,
 *  never the browser's broken-image "?" icon. */
export function Flag({
  team,
  size = 28,
  className,
}: {
  team: string;
  size?: number;
  className?: string;
}) {
  const url = localFlag(team);
  const [failed, setFailed] = useState(false);

  if (!url || failed) {
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
      decoding="async"
      onError={() => setFailed(true)}
      className={cn("shrink-0 rounded-full object-cover ring-1 ring-border/80", className)}
      style={{ width: size, height: size }}
    />
  );
}
