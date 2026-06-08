"use client";

import { useState } from "react";
import { trackEvent } from "@/lib/analytics";
import { cn } from "@/lib/utils";

/** Share the current page: native share sheet on mobile, copy-link fallback. */
export function ShareButton({
  title,
  label = "Share",
  className,
}: {
  title?: string;
  label?: string;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);

  const onShare = async () => {
    if (typeof window === "undefined") return;
    const url = window.location.href;
    trackEvent("share", { path: window.location.pathname });
    const shareTitle = title ?? document.title;
    if (navigator.share) {
      try {
        await navigator.share({ title: shareTitle, url });
        return;
      } catch {
        /* user cancelled — fall through to copy */
      }
    }
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard blocked — nothing more we can do */
    }
  };

  return (
    <button
      type="button"
      onClick={onShare}
      aria-label="Share this page"
      className={cn(
        "inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm font-medium text-muted transition hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-win/50",
        className,
      )}
    >
      <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
        <circle cx="18" cy="5" r="3" /><circle cx="6" cy="12" r="3" /><circle cx="18" cy="19" r="3" />
        <path d="M8.6 13.5l6.8 4M15.4 6.5l-6.8 4" strokeLinecap="round" />
      </svg>
      {copied ? "Link copied!" : label}
    </button>
  );
}
