"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ENGAGEMENT_EVENT, isEngaged } from "@/lib/engagement";
import { trackEvent } from "@/lib/analytics";

/** Chromium's install event (not in lib.dom — still spec-proposal). */
interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

const DISMISS_KEY = "finalwhistle:install-prompt-dismissed:v1";

/** Grace period after an in-session engagement signal before the prompt may
 *  appear. Engagement crosses on the *first* pick, so showing the prompt
 *  instantly would pop it over the prediction the user just made. A short defer
 *  lets them finish; returning users (already engaged on load) are unaffected. */
let settleMs = 6000;

/** @internal Test hook — shorten the grace period so specs don't wait 6s. */
export function __setInstallPromptSettleMs(ms: number): void {
  settleMs = ms;
}

function loadDismissed(): boolean {
  try {
    return window.localStorage.getItem(DISMISS_KEY) === "1";
  } catch {
    return false;
  }
}

function isStandalone(): boolean {
  // matchMedia is optional-chained for jsdom; navigator.standalone is iOS-only.
  return (
    window.matchMedia?.("(display-mode: standalone)")?.matches === true ||
    (navigator as { standalone?: boolean }).standalone === true
  );
}

function isIOS(): boolean {
  const ua = navigator.userAgent;
  // iPadOS 13+ masquerades as macOS but is touch-capable.
  return /iPhone|iPad|iPod/i.test(ua) || (/Macintosh/i.test(ua) && navigator.maxTouchPoints > 1);
}

export type InstallPlatform = "android" | "ios";

/**
 * Install-prompt state machine (PRD FR 4.4):
 *  - never on first load: only once an engagement signal has been recorded;
 *  - never when already installed/standalone;
 *  - Android/Chromium: captures `beforeinstallprompt` and re-fires it natively;
 *  - iOS/Safari: no event exists — exposes platform "ios" so the UI can show
 *    manual Add-to-Home-Screen steps;
 *  - dismissing persists permanently (localStorage).
 */
export function useInstallPrompt(): {
  visible: boolean;
  platform: InstallPlatform | null;
  promptInstall: () => Promise<void>;
  dismiss: () => void;
} {
  const [ready, setReady] = useState(false); // hydration gate (SSR match)
  const [engaged, setEngaged] = useState(false);
  const [dismissed, setDismissed] = useState(true);
  const [installed, setInstalled] = useState(false);
  const [canNativePrompt, setCanNativePrompt] = useState(false);
  const deferredRef = useRef<BeforeInstallPromptEvent | null>(null);

  useEffect(() => {
    // Returning users who were already engaged see the prompt immediately —
    // they aren't mid-action on a fresh load.
    setEngaged(isEngaged());
    setDismissed(loadDismissed());
    setInstalled(isStandalone());
    setReady(true);

    let settleTimer: number | null = null;

    const onBip = (e: Event) => {
      e.preventDefault(); // we re-fire it from our own UI at the right moment
      deferredRef.current = e as BeforeInstallPromptEvent;
      setCanNativePrompt(true);
    };
    const onInstalled = () => {
      trackEvent("app_installed");
      setInstalled(true);
    };
    // An in-session signal (e.g. the user's first pick) crosses engagement —
    // defer so the prompt doesn't interrupt the action that triggered it.
    const onEngagement = () => {
      if (!isEngaged() || settleTimer != null) return;
      settleTimer = window.setTimeout(() => {
        settleTimer = null;
        setEngaged(true);
      }, settleMs);
    };

    window.addEventListener("beforeinstallprompt", onBip);
    window.addEventListener("appinstalled", onInstalled);
    window.addEventListener(ENGAGEMENT_EVENT, onEngagement);
    window.addEventListener("storage", onEngagement); // cross-tab
    return () => {
      window.removeEventListener("beforeinstallprompt", onBip);
      window.removeEventListener("appinstalled", onInstalled);
      window.removeEventListener(ENGAGEMENT_EVENT, onEngagement);
      window.removeEventListener("storage", onEngagement);
      if (settleTimer != null) window.clearTimeout(settleTimer);
    };
  }, []);

  const dismiss = useCallback(() => {
    try {
      window.localStorage.setItem(DISMISS_KEY, "1");
    } catch {
      /* non-fatal */
    }
    setDismissed(true);
    trackEvent("install_prompt_dismissed");
  }, []);

  const promptInstall = useCallback(async () => {
    const deferred = deferredRef.current;
    if (!deferred) return;
    deferredRef.current = null;
    setCanNativePrompt(false);
    await deferred.prompt();
    const choice = await deferred.userChoice;
    trackEvent(choice.outcome === "accepted" ? "install_prompt_accepted" : "install_prompt_declined");
    if (choice.outcome !== "accepted") dismiss(); // they said no — don't nag again
  }, [dismiss]);

  const platform: InstallPlatform | null = canNativePrompt
    ? "android"
    : ready && isIOS()
      ? "ios"
      : null;

  const visible = ready && engaged && !dismissed && !installed && platform !== null;

  return { visible, platform: visible ? platform : null, promptInstall, dismiss };
}
