"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { notifyBridge } from "@/lib/session";
import { getLeagueSeasonLeaderboard } from "@/lib/leagueTips";
import { DEFAULT_LEAGUE } from "@/lib/leagueConfig";
import type { MatchSummary } from "@/lib/types";

const DISMISS_KEY = "fw_bridge_dismissed_v1";
const BRIDGE_SOURCE = "wc26_final_bridge";

function loadDismissed(): boolean {
  try {
    return window.localStorage.getItem(DISMISS_KEY) === "1";
  } catch {
    return false;
  }
}

/** True once the World Cup final (Match.stage === "final") has been played out —
 *  the same matches feed the home dashboard already polls, never a hardcoded
 *  date/clock check (kickoff can slip). */
export function isFinalFinished(matches: MatchSummary[]): boolean {
  return matches.some((m) => m.stage === "final" && m.status === "finished");
}

type SubmitStatus = "idle" | "submitting" | "success" | "error";

/**
 * Post-final "what's next" bridge (WC26 → NRL + domestic-league email list).
 * A dismissible card, never a modal — the World Cup traffic wedge expires the
 * moment the final whistle blows, so this is the one banner that converts it.
 * Shown only once `matches` shows the final as finished; dismissal is
 * permanent (localStorage), mirroring InstallAppPrompt's pattern.
 */
export function RetentionBridge({ matches }: { matches: MatchSummary[] }) {
  const [ready, setReady] = useState(false); // hydration gate (SSR match)
  const [dismissed, setDismissed] = useState(true);
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<SubmitStatus>("idle");
  // Whether the league loop actually has data behind it yet -- design doc:
  // "retention-bridge copy updated to point at /tips WHEN THE LEAGUE GOES
  // LIVE." The frontend deploys to Vercel at merge, well before the
  // migration reaches prod via refresh.yml and before the separate,
  // stop-gated pipeline_target flip that starts ingesting fixtures (CLAUDE.md
  // sequencing) -- a hardcoded "true" here would claim the loop is live
  // during that whole window. Defaults to false (fail closed: never assert
  // "live" without confirmation) and flips true only once the public season
  // leaderboard resolves instead of 404ing league_not_found/league_inactive.
  const [leagueLive, setLeagueLive] = useState(false);

  useEffect(() => {
    setDismissed(loadDismissed());
    setReady(true);
  }, []);

  const finalFinished = isFinalFinished(matches);
  useEffect(() => {
    if (!ready || dismissed || !finalFinished) return;
    let live = true;
    getLeagueSeasonLeaderboard(DEFAULT_LEAGUE)
      .then(() => {
        if (live) setLeagueLive(true);
      })
      .catch(() => {
        if (live) setLeagueLive(false); // league_not_found / league_inactive / any other error -- not live
      });
    return () => {
      live = false;
    };
  }, [ready, dismissed, finalFinished]);

  const dismiss = () => {
    try {
      window.localStorage.setItem(DISMISS_KEY, "1");
    } catch {
      /* non-fatal — worst case it reappears next visit */
    }
    setDismissed(true);
  };

  if (!ready || dismissed || !finalFinished) return null;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setStatus("submitting");
    try {
      await notifyBridge(email, BRIDGE_SOURCE);
      setStatus("success");
    } catch {
      setStatus("error");
    }
  }

  return (
    <div
      role="region"
      aria-label="What's next after the World Cup"
      className="glass mx-auto mb-6 max-w-2xl rounded-2xl p-5"
      onKeyDown={(e) => {
        if (e.key === "Escape") dismiss();
      }}
    >
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <h2 className="font-display text-lg font-extrabold tracking-tight">
            The World Cup is over. The AI is still playing.
          </h2>
          <p className="mt-1 text-sm text-muted">
            FinalWhistle&rsquo;s model now runs on the NRL — live predictions, every round.
          </p>
          <Link
            href="/nrl/matches"
            className="mt-3 inline-flex items-center gap-2 rounded-xl bg-win px-5 py-2.5 text-sm font-bold text-pitch transition hover:brightness-105"
          >
            See NRL predictions
          </Link>

          <div className="mt-4 border-t border-border pt-4">
            {leagueLive ? (
              // Confirmed live (the public season leaderboard resolved, not
              // 404) -- only now is "tips are live" a true claim.
              <>
                <p className="text-sm text-muted">
                  Premier League tips are live — predict every fixture&rsquo;s scoreline and beat the AI.
                </p>
                <Link
                  href="/tips"
                  className="mt-2 inline-flex items-center gap-2 rounded-xl border border-border bg-surface-2 px-4 py-2 text-sm font-bold text-foreground transition hover:border-win/40"
                >
                  Play Premier League tips
                </Link>
              </>
            ) : (
              // Not live yet (or not confirmed) -- the honest fallback is
              // the email-capture path this copy already promised.
              <>
                <p className="text-sm text-muted">Get one email when your league kicks off.</p>
                {/* Persistent container so the live region exists before the content
                 *  swap — a screen reader can miss an announcement from a region
                 *  that's inserted at the same moment as its text. */}
                <div aria-live="polite">
                  {status === "success" ? (
                    <p className="mt-2 text-sm font-semibold text-lime-deep">
                      Done — one email, mid-August, no spam.
                    </p>
                  ) : (
                    <form onSubmit={handleSubmit} className="mt-2 flex flex-col gap-2 sm:flex-row">
                      <label htmlFor="bridge-email" className="sr-only">
                        Email address
                      </label>
                      <input
                        id="bridge-email"
                        type="email"
                        required
                        autoComplete="email"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                        placeholder="Email address"
                        className="w-full min-w-0 flex-1 rounded-lg border border-border bg-surface px-3 py-2.5 text-sm text-foreground outline-none transition focus:border-win sm:w-auto"
                      />
                      <button
                        type="submit"
                        disabled={status === "submitting"}
                        className="shrink-0 rounded-lg border border-border bg-surface-2 px-4 py-2.5 text-sm font-bold text-foreground transition hover:bg-border disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        {status === "submitting" ? "Please wait…" : "Notify me"}
                      </button>
                    </form>
                  )}
                </div>
                {status === "error" && (
                  <p role="alert" className="mt-2 text-xs font-medium text-loss">
                    Something went wrong — please try again.
                  </p>
                )}
              </>
            )}
          </div>
        </div>
        <button
          type="button"
          onClick={dismiss}
          aria-label="Dismiss"
          className="shrink-0 rounded-md p-1 text-muted transition hover:bg-surface-2 hover:text-foreground"
        >
          <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
          </svg>
        </button>
      </div>
    </div>
  );
}
