"use client";

import { useEffect, useRef } from "react";
import Image from "next/image";
import { useInstallPrompt } from "@/lib/useInstallPrompt";
import { trackEvent } from "@/lib/analytics";

/** Engagement-gated "install the app" card (PRD FR 4.4). Bottom-anchored and
 *  dismissible — never a blocking modal, never on first load, never while
 *  already installed. Android gets the native install flow; iOS gets manual
 *  Add-to-Home-Screen steps (Safari has no install event). */
export function InstallAppPrompt() {
  const { visible, platform, promptInstall, dismiss } = useInstallPrompt();

  // One "shown" event per appearance, not per re-render.
  const shownRef = useRef(false);
  useEffect(() => {
    if (visible && !shownRef.current) {
      shownRef.current = true;
      trackEvent("install_prompt_shown", { platform: platform ?? "unknown" });
    }
  }, [visible, platform]);

  if (!visible) return null;

  return (
    <div
      role="complementary"
      aria-label="Install FinalWhistle"
      className="glass safe-x fixed inset-x-3 bottom-[calc(4.5rem+env(safe-area-inset-bottom))] z-40 mx-auto max-w-md rounded-2xl border border-win/25 p-4 shadow-xl sm:inset-x-auto sm:bottom-6 sm:right-6"
    >
      <div className="flex items-start gap-3">
        <Image
          src="/icon-192.png"
          alt=""
          width={40}
          height={40}
          className="shrink-0 rounded-xl"
        />
        <div className="min-w-0 flex-1">
          <p className="font-display text-sm font-bold">Install FinalWhistle</p>
          {platform === "android" ? (
            <p className="mt-0.5 text-xs leading-relaxed text-muted">
              Full-screen launch from your home screen — your bracket and live
              scores, one tap away.
            </p>
          ) : (
            <p className="mt-0.5 text-xs leading-relaxed text-muted">
              Tap{" "}
              <span className="font-semibold text-foreground">
                Share{" "}
                <svg viewBox="0 0 24 24" className="inline h-3.5 w-3.5 align-[-2px]" fill="none" stroke="currentColor" strokeWidth="2" aria-label="Share icon">
                  <path d="M12 3v12M8 7l4-4 4 4M5 11v8a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-8" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </span>{" "}
              then <span className="font-semibold text-foreground">“Add to Home Screen”</span> to
              install the app.
            </p>
          )}
          {platform === "android" && (
            <button
              type="button"
              onClick={() => void promptInstall()}
              className="mt-2.5 rounded-lg bg-win/15 px-3.5 py-1.5 text-xs font-semibold text-win ring-1 ring-win/30 transition hover:bg-win/25"
            >
              Install app
            </button>
          )}
        </div>
        <button
          type="button"
          onClick={dismiss}
          aria-label="Dismiss install prompt"
          className="shrink-0 rounded-md p-1 text-muted transition hover:text-foreground"
        >
          <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
          </svg>
        </button>
      </div>
    </div>
  );
}
