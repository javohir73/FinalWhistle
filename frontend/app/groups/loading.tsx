import { Skeleton, SkeletonScreen, SkeletonRows } from "@/components/Skeleton";

/** Route-level fallback for /groups (App Router). GroupsClient is server-seeded,
 *  so this shows only while page.tsx awaits the standings feed on a cold
 *  navigation. Mirrors the header plus the two-column group-table grid — one
 *  SkeletonRows glass card per group, four rows each (a WC26 group's four teams)
 *  — so the box is reserved and the tables drop in without shifting. */
export default function GroupsLoading() {
  return (
    <SkeletonScreen label="Loading groups…">
      {/* "Group tables" header block. */}
      <div className="mb-8">
        <Skeleton className="h-9 w-56 rounded" />
        <Skeleton className="mt-2 h-4 w-72 rounded" />
      </div>
      <div className="grid gap-5 md:grid-cols-2">
        {Array.from({ length: 8 }).map((_, i) => (
          <SkeletonRows key={i} rows={4} />
        ))}
      </div>
    </SkeletonScreen>
  );
}
