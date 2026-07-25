import { Skeleton, SkeletonScreen, SkeletonCardGrid } from "@/components/Skeleton";

/** Route-level fallback for /matches (App Router). page.tsx is an async server
 *  component that awaits the fixture feed, so on a cold navigation Next streams
 *  this in first. Mirrors the page's header + fixture card grid so the box is
 *  reserved and nothing shifts when the real fixtures land (design doc:
 *  Floodlight P6 skeletons). Reuses the shared shimmer primitives. */
export default function MatchesLoading() {
  return (
    <SkeletonScreen label="Loading fixtures…">
      {/* Title + subtitle, standing in for the "All Fixtures" header block. */}
      <div className="mb-6">
        <Skeleton className="h-9 w-52 rounded" />
        <Skeleton className="mt-2 h-4 w-36 rounded" />
      </div>
      {/* Search field, "Beat the AI" promo, and the Upcoming/Live/Finished
       *  filter tabs all sit above the grid in MatchesClient — reserve them so
       *  the fixtures don't jump down when the client hydrates (no CLS). */}
      <Skeleton className="mb-4 h-12 w-full rounded-2xl" />
      <Skeleton className="mb-6 h-20 w-full rounded-2xl" />
      <div className="mb-6 flex gap-1 rounded-[14px] bg-surface-2 p-1">
        <Skeleton className="h-10 flex-1 rounded-[11px]" />
        <Skeleton className="h-10 flex-1 rounded-[11px]" />
        <Skeleton className="h-10 flex-1 rounded-[11px]" />
      </div>
      <SkeletonCardGrid />
    </SkeletonScreen>
  );
}
