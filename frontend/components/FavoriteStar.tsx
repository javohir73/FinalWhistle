"use client";

import { useFavorites } from "@/lib/useFavorites";
import { cn } from "@/lib/utils";

/** Star toggle for marking a team as a favorite. Safe to place inside a link —
 *  it prevents the click from navigating. */
export function FavoriteStar({
  team,
  size = 16,
  className,
}: {
  team: string;
  size?: number;
  className?: string;
}) {
  const { isFavorite, toggle } = useFavorites();
  const active = isFavorite(team);

  return (
    <button
      type="button"
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        toggle(team);
      }}
      aria-pressed={active}
      aria-label={active ? `Remove ${team} from favorites` : `Add ${team} to favorites`}
      title={active ? "Favorited" : "Add to favorites"}
      className={cn(
        "grid place-items-center rounded-md p-1 transition hover:bg-surface-2/70",
        active ? "text-gold" : "text-muted/50 hover:text-muted",
        className,
      )}
    >
      <svg
        width={size}
        height={size}
        viewBox="0 0 24 24"
        fill={active ? "currentColor" : "none"}
        stroke="currentColor"
        strokeWidth="2"
        strokeLinejoin="round"
      >
        <path d="M12 2l3 6.5 7 .7-5.2 4.8 1.5 6.9L12 17.8 5.7 20.9l1.5-6.9L2 9.2l7-.7z" />
      </svg>
    </button>
  );
}
