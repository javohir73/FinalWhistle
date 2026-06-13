"use client";

import { useState } from "react";
import { flagUrl, teamInitials } from "@/lib/flags";
import { cn } from "@/lib/utils";

/** Rounded flag chip. Loads the flag from flagcdn (a remote CDN) with a plain
 *  <img> — these are tiny, so next/image isn't worth it.
 *
 *  Reliability: on a cold load the chooser fires ~48 flag requests at once and
 *  the free CDN can drop a few. Without handling, the browser paints its ugly
 *  broken-image icon. So we retry once (cache-busted, which recovers transient
 *  failures so the flag still appears) and only then fall back to a clean
 *  typographic chip — never the browser's "?" placeholder. */
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
  // 0 = first try, 1 = retried; >= 2 means both attempts failed → initials.
  const [attempt, setAttempt] = useState(0);

  if (!url || attempt >= 2) {
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

  // Cache-bust the retry so the browser refetches instead of replaying its
  // poisoned failed-response cache entry.
  const src = attempt === 0 ? url : `${url}?r=${attempt}`;

  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      key={src}
      src={src}
      alt=""
      aria-hidden
      width={size}
      height={size}
      loading="lazy"
      decoding="async"
      referrerPolicy="no-referrer"
      onError={() => setAttempt((a) => a + 1)}
      className={cn("shrink-0 rounded-full object-cover ring-1 ring-border/80", className)}
      style={{ width: size, height: size }}
    />
  );
}
