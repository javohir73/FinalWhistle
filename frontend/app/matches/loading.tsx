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
      <SkeletonCardGrid />
    </SkeletonScreen>
  );
}
