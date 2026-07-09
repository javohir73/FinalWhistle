"use client";

import { usePathname } from "next/navigation";

/** Hides server-rendered chrome (disclaimer banner, footer, ...) on
 *  /embed/[matchId] — a standalone, partner-iframeable widget that must not
 *  carry the full site chrome. The components it wraps (e.g. DisclaimerBanner)
 *  aren't themselves client components, so the pathname check is lifted into
 *  this thin client wrapper instead of pulling usePathname into each one. */
export function HideOnEmbed({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  if (pathname === "/embed" || pathname.startsWith("/embed/")) return null;
  return <>{children}</>;
}
