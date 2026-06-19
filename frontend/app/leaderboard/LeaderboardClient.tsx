"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getLeaderboard } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { useAuth } from "@/components/AuthProvider";
import { useFavorites } from "@/lib/useFavorites";
import { getMyBracket } from "@/lib/session";
import { Loading, ErrorState, Empty } from "@/components/States";
import { Flag } from "@/components/Flag";
import { MyRankCard } from "@/components/MyRankCard";
import { LocationPicker } from "@/components/LocationPicker";
import { InstallAppPrompt } from "@/components/InstallAppPrompt";
import { useInstallPrompt } from "@/lib/useInstallPrompt";
import type { LeaderboardRow, SavedBracket } from "@/lib/types";

/** Initials for the avatar — first letters of up to two name words, else the
 *  first two characters of the email local part. */
function initialsFor(name?: string | null, email?: string | null): string {
  const n = name?.trim();
  if (n) {
    const parts = n.split(/\s+/).filter(Boolean);
    return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || n.slice(0, 2).toUpperCase();
  }
  const local = email?.split("@")[0] ?? "";
  return local.slice(0, 2).toUpperCase() || "··";
}

export function LeaderboardClient({ initialRows }: { initialRows?: LeaderboardRow[] }) {
  const state = useFetch(getLeaderboard, [], undefined, initialRows);
  const { user, openSignIn } = useAuth();
  const { favorites } = useFavorites();
  // "Install app" settings row — only meaningful when a native prompt is queued.
  const install = useInstallPrompt();

  // The signed-in user's saved bracket drives the stat row (rank / points).
  const [bracket, setBracket] = useState<SavedBracket | null>(null);
  useEffect(() => {
    if (!user) {
      setBracket(null);
      return;
    }
    let live = true;
    (async () => {
      try {
        const b = await getMyBracket();
        if (live) setBracket(b);
      } catch {
        /* ignore — stats fall back to placeholders */
      }
    })();
    return () => {
      live = false;
    };
  }, [user]);

  const rows = state.status === "success" ? state.data : [];
  // Match the signed-in player's leaderboard row by display name so we can both
  // highlight their row and surface a "Correct" stat (percentile) when present.
  const myName = bracket?.display_name?.trim() || user?.display_name?.trim() || null;
  const myRow = myName ? rows.find((r) => r.display_name === myName) : undefined;

  const rank = bracket?.score?.rank ?? myRow?.rank ?? null;
  const points = bracket?.score?.total_points ?? myRow?.total_points ?? null;
  const correct = myRow?.percentile != null ? `${myRow.percentile}%` : null;

  const name = user?.display_name?.trim() || user?.email?.split("@")[0] || "Guest";
  const followingCount = favorites.length;
  const statusLine = user
    ? followingCount > 0
      ? `Signed in · Following ${followingCount}`
      : "Signed in"
    : "Guest · picks saved on this device";

  return (
    <div className="space-y-5">
      {/* 1 · Profile header */}
      <header className="fade-up flex items-center gap-4">
        {user?.avatar_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={user.avatar_url}
            alt=""
            aria-hidden
            className="h-16 w-16 shrink-0 rounded-full object-cover ring-1 ring-border"
          />
        ) : (
          <span
            aria-hidden
            className="grid h-16 w-16 shrink-0 place-items-center rounded-full bg-pitch font-display text-xl font-extrabold text-win"
          >
            {initialsFor(user?.display_name, user?.email)}
          </span>
        )}
        <div className="min-w-0">
          <h1 className="font-display text-2xl font-extrabold tracking-tight sm:text-3xl">
            {name}
          </h1>
          <p className="mt-1 truncate text-sm text-muted">{statusLine}</p>
        </div>
      </header>

      {/* 2 · Stat row */}
      <div className="grid grid-cols-3 gap-3">
        <Stat label="Rank" value={rank != null ? `#${rank}` : "—"} />
        <Stat label="Points" value={points != null ? `${points}` : "—"} />
        <Stat label="Correct" value={correct ?? "—"} />
      </div>

      {/* 3 · Sign-in prompt (guests only) */}
      {!user && (
        <section className="panel-pitch rounded-2xl p-5">
          <h2 className="font-display text-lg font-extrabold text-white">
            Save across devices
          </h2>
          <p className="mt-1.5 text-sm leading-relaxed text-[#a9c7b4]">
            Free account — sync your bracket and join the leaderboard. Your picks stay yours.
          </p>
          <button
            type="button"
            onClick={() => openSignIn()}
            className="mt-4 inline-flex items-center gap-1 rounded-xl bg-win px-4 py-2.5 font-display text-sm font-bold text-pitch transition hover:brightness-105"
          >
            Create free account →
          </button>
        </section>
      )}

      {/* 4 · Leaderboard */}
      <section>
        <h2 className="mb-2.5 px-0.5 text-[11px] font-semibold uppercase tracking-wider text-muted">
          Leaderboard
        </h2>
        <p className="mb-3 max-w-xl px-0.5 text-sm text-muted">
          Public brackets ranked by points (group 3 · knockout 5 · finalist 10 · champion 20).
          Build yours on the{" "}
          <Link href="/my-bracket" className="text-lime-deep underline underline-offset-2">
            My Bracket
          </Link>{" "}
          page, then join.
        </p>

        <MyRankCard />

        {state.status === "loading" && <Loading label="Loading leaderboard…" />}
        {state.status === "error" && <ErrorState message={state.message} />}
        {state.status === "success" &&
          (rows.length === 0 ? (
            <Empty label="No public brackets yet — be the first to join from My Bracket." />
          ) : (
            <div className="glass overflow-x-auto rounded-2xl p-2 sm:p-4">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-[11px] uppercase tracking-wider text-muted">
                    <th className="px-2 pb-2 text-left font-medium">#</th>
                    <th className="px-2 pb-2 text-left font-medium">Player</th>
                    <th className="px-2 pb-2 text-left font-medium">Champion pick</th>
                    <th className="px-2 pb-2 text-right font-medium">Points</th>
                    <th className="hidden px-2 pb-2 text-right font-medium sm:table-cell">Top</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, i) => {
                    const isMe = myName != null && row.display_name === myName;
                    const placeRank = row.rank ?? i + 1;
                    return (
                      <tr
                        key={`${row.display_name}-${i}`}
                        className={`border-t border-border ${isMe ? "bg-win/[0.06]" : ""}`}
                      >
                        <td
                          className={`px-2 py-2.5 font-semibold tabular-nums ${
                            placeRank === 1 ? "text-gold" : "text-muted"
                          }`}
                        >
                          {placeRank}
                        </td>
                        <td className={`px-2 py-2.5 ${isMe ? "font-bold" : "font-medium"}`}>
                          {row.display_name}
                        </td>
                        <td className="px-2 py-2.5">
                          {row.champion ? (
                            <span className="flex items-center gap-2">
                              <Flag team={row.champion} size={18} />
                              <span className="min-w-0 truncate">{row.champion}</span>
                            </span>
                          ) : (
                            <span className="text-muted">—</span>
                          )}
                        </td>
                        <td className="px-2 py-2.5 text-right font-display font-bold tabular-nums">
                          {row.total_points}
                        </td>
                        <td className="hidden px-2 py-2.5 text-right tabular-nums text-muted sm:table-cell">
                          {row.percentile != null ? `${row.percentile}%` : "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ))}
      </section>

      {/* 5 · Favourites */}
      <section>
        <h2 className="mb-2.5 px-0.5 text-[11px] font-semibold uppercase tracking-wider text-muted">
          Favourites
        </h2>
        <div className="glass rounded-2xl p-4">
          {favorites.length > 0 ? (
            <ul className="flex flex-wrap gap-2.5">
              {favorites.map((team) => (
                <li
                  key={team}
                  className="inline-flex items-center gap-2 rounded-full bg-surface-2 px-3 py-1.5 text-sm font-semibold"
                >
                  <Flag team={team} size={18} />
                  {team}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">Tap the ★ on any team to follow them here.</p>
          )}
        </div>
      </section>

      {/* 6 · Settings & info */}
      <section>
        <h2 className="mb-2.5 px-0.5 text-[11px] font-semibold uppercase tracking-wider text-muted">
          Settings &amp; info
        </h2>
        <div className="glass overflow-hidden rounded-2xl">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2.5 px-4 py-3.5">
            <RowIcon>
              <circle cx="12" cy="12" r="9" />
              <path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" />
            </RowIcon>
            <span className="text-sm font-semibold">Time zone</span>
            <div className="ml-auto min-w-0 flex-1 sm:flex-none">
              <LocationPicker />
            </div>
          </div>

          {install.platform === "android" && (
            <RowButton label="Install app" onClick={() => void install.promptInstall()}>
              <path d="M12 3v11M8 11l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M5 19h14" strokeLinecap="round" />
            </RowButton>
          )}

          <RowLink href="/about" label="How it works">
            <circle cx="12" cy="12" r="9" />
            <path d="M12 11v5M12 8h.01" strokeLinecap="round" />
          </RowLink>

          <RowLink href="/methodology" label="Methodology">
            <path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15H6.5A2.5 2.5 0 0 0 4 20.5V5.5Z" strokeLinejoin="round" />
            <path d="M4 20.5A2.5 2.5 0 0 1 6.5 18H20" strokeLinejoin="round" />
          </RowLink>
        </div>
      </section>

      {/* 7 · Footer */}
      <footer className="px-0.5 pb-2 pt-2 text-center text-[11px] leading-relaxed text-muted">
        <p>
          FinalWhistle · For analytics and entertainment only.{" "}
          <strong className="font-semibold text-foreground">Not betting advice.</strong>
        </p>
        <p className="mt-1">
          <Link href="/privacy" className="text-lime-deep underline-offset-2 hover:underline">
            Privacy
          </Link>{" "}
          ·{" "}
          <Link href="/terms" className="text-lime-deep underline-offset-2 hover:underline">
            Terms &amp; support
          </Link>
        </p>
      </footer>

      {/* Engagement-gated install card (self-managing visibility) */}
      <InstallAppPrompt />
    </div>
  );
}

/** A light stat card in the three-up row. */
function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="glass rounded-2xl px-3 py-4 text-center">
      <p className="font-display text-2xl font-extrabold tabular-nums">{value}</p>
      <p className="mt-0.5 text-[11px] font-semibold text-muted">{label}</p>
    </div>
  );
}

/** Tinted square icon used by the settings rows. */
function RowIcon({ children }: { children: React.ReactNode }) {
  return (
    <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-surface-2 text-lime-deep">
      <svg viewBox="0 0 24 24" className="h-[18px] w-[18px]" fill="none" stroke="currentColor" strokeWidth="2">
        {children}
      </svg>
    </span>
  );
}

/** A tappable settings row that runs an action (same look as RowLink). */
function RowButton({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center gap-3 border-t border-border px-4 py-3.5 text-left transition hover:bg-surface-2"
    >
      <RowIcon>{children}</RowIcon>
      <span className="text-sm font-semibold">{label}</span>
      <svg
        viewBox="0 0 24 24"
        className="ml-auto h-4 w-4 text-muted"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        aria-hidden
      >
        <path d="M9 6l6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </button>
  );
}

/** A tappable settings/info row with an icon, label and chevron. */
function RowLink({
  href,
  label,
  children,
}: {
  href: string;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      className="flex items-center gap-3 border-t border-border px-4 py-3.5 transition hover:bg-surface-2"
    >
      <RowIcon>{children}</RowIcon>
      <span className="text-sm font-semibold">{label}</span>
      <svg
        viewBox="0 0 24 24"
        className="ml-auto h-4 w-4 text-muted"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        aria-hidden
      >
        <path d="M9 6l6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </Link>
  );
}
