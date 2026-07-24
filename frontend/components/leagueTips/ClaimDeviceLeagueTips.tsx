"use client";

import { useEffect, useRef } from "react";
import { useAuth } from "@/components/AuthProvider";
import { getOrCreateDeviceId } from "@/lib/session";
import { claimLeagueTips } from "@/lib/leagueTips";

/** Merge-on-signup for the league beat-the-AI loop (design doc: League Score
 *  Predictions, 2026-07-24) -- identical idiom to components/nrl/
 *  ClaimDeviceTips, duplicated locally rather than imported (this codebase
 *  already keeps each vertical's copy of a shared tip_players idiom local,
 *  see backend/app/api/league_score_predictions.py's own docstring on the
 *  same point). Renders nothing -- a side-effect-only component.
 *
 *  Fires once per signed-in account per mount (the ref guard keyed on
 *  user.id): claimLeagueTips is idempotent server-side, but there's no reason
 *  to hit it on every render. If the user signs in while already on the
 *  page, `user` flips from null to set and the effect fires then too. */
export function ClaimDeviceLeagueTips() {
  const { user } = useAuth();
  const claimedForRef = useRef<number | null>(null);

  useEffect(() => {
    if (!user || claimedForRef.current === user.id) return;
    const deviceId = getOrCreateDeviceId();
    if (!deviceId) return;
    claimedForRef.current = user.id;
    claimLeagueTips(deviceId).catch(() => {
      // Best-effort -- a failed claim isn't surfaced; a later mount/sign-in
      // retries it, and nothing on this page depends on it having run yet.
    });
  }, [user]);

  return null;
}
