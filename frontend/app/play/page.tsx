import type { Metadata } from "next";
import { getNrlTipsheetServer } from "@/lib/api";
import { PlayHub } from "./PlayHub";

// Same ISR posture as /nrl/tips and /tips -- the shell is evergreen (nothing
// user-specific here; picks and leaderboards resolve inside the client
// sections), so the round rolls week to week under one stable URL.
export const revalidate = 300;

export const metadata: Metadata = {
  title: "Play — beat the AI across every competition",
  description:
    "One place to make your picks against the model: the World Cup bracket, league score tips, and this week's NRL round — every pick graded on a public record.",
  alternates: { canonical: "/play" },
};

/** The Floodlight Play hub (design: Floodlight Implementation Plan, P5). Merges
 *  the WC26 bracket, league tips and NRL tips into one surface grouped by sport.
 *  Server-fetches the current NRL round to seed the NRL group (same call as
 *  /nrl/tips), degrading honestly to null when the endpoint has no data -- the
 *  hub still renders both groups. League tips carry no public seed (they resolve
 *  client-side, exactly as /tips does today), so nothing is fetched for them
 *  here. */
export default async function PlayPage() {
  const nrlTipsheet = await getNrlTipsheetServer().catch(() => null);

  return <PlayHub nrlTipsheet={nrlTipsheet} />;
}
