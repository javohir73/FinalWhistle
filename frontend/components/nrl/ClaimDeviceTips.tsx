"use client";

import { useEffect, useRef } from "react";
import { useAuth } from "@/components/AuthProvider";
import { getOrCreateDeviceId } from "@/lib/session";
import { claimNrlTips } from "@/lib/nrlTips";

/** Merge-on-signup for the beat-the-AI loop (design doc: NRL Round Tips,
 *  Slice 2): once a device is signed in, attach its tip history to the
 *  account so its display name follows the account from then on. Renders
 *  nothing -- a side-effect-only component, same shape as ActivityPing.
 *
 *  Fires once per signed-in account per mount (the ref guard keyed on
 *  user.id): the endpoint is idempotent server-side, but there's no reason
 *  to hit it on every render. If the user signs in while already on the
 *  page, `user` flips from null to set and the effect fires then too. */
export function ClaimDeviceTips() {
  const { user } = useAuth();
  const claimedForRef = useRef<number | null>(null);

  useEffect(() => {
    if (!user || claimedForRef.current === user.id) return;
    const deviceId = getOrCreateDeviceId();
    if (!deviceId) return;
    claimedForRef.current = user.id;
    claimNrlTips(deviceId).catch(() => {
      // Best-effort -- a failed claim isn't surfaced; a later mount/sign-in
      // retries it, and nothing on this page depends on it having run yet.
    });
  }, [user]);

  return null;
}
