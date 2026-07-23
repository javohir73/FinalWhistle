import { Loading } from "@/components/States";

/** Skeleton for round permalinks not covered by generateStaticParams (see
 *  page.tsx) -- current/next render at deploy, everything else (last week's
 *  round, the archive) renders on demand and needs a visible loading state
 *  rather than blocking the visitor on a cold API call (design doc: NRL
 *  Round Tips, Slice 1 rendering bullet). */
export default function NrlRoundLoading() {
  return <Loading label="Loading round tips…" />;
}
