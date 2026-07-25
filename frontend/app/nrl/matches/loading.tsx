import { Skeleton, SkeletonScreen, SkeletonCardGrid } from "@/components/Skeleton";

/** Route-level fallback for /nrl/matches (App Router). page.tsx awaits the NRL
 *  fixture feed before it can seed MatchesClient, so on a cold navigation Next
 *  streams this in first. Mirrors the "NRL fixtures" header, the segmented
 *  Upcoming/Live/Finished control and the fixture card grid so the box is
 *  reserved and nothing shifts when the real fixtures land (design doc:
 *  Floodlight P6 skeletons). Reuses the shared shimmer primitives. */
export default function NrlMatchesLoading() {
  return (
    <SkeletonScreen label="Loading fixtures…">
      {/* "NRL fixtures" title. */}
      <Skeleton className="h-8 w-44 rounded" />

      {/* Segmented Upcoming / Live / Finished control — mirrors the tablist
          container so the grid below it doesn't jump when the tabs paint. */}
      <div className="mb-6 mt-4 flex gap-1 rounded-[14px] bg-surface-2 p-1">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-9 flex-1 rounded-[11px]" />
        ))}
      </div>

      <SkeletonCardGrid />
    </SkeletonScreen>
  );
}
