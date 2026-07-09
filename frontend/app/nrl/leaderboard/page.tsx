import type { Metadata } from "next";
import { APP_NAME } from "@/lib/constants";

export { default } from "../../leaderboard/page";

/** Alias of /leaderboard so the pathname carries NRL context (see lib/sports.ts).
 *  Same title as the source page; canonical points back at /leaderboard so
 *  search engines don't index this as duplicate content. */
export const metadata: Metadata = {
  title: `${APP_NAME} — FIFA World Cup 2026 Predictions`,
  alternates: { canonical: "/leaderboard" },
};
