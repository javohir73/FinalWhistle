// Floodlight P1 slice p1-s3: colocates the OG image convention file for this
// segment. Next resolves opengraph-image by walking the *matched route's own*
// segment tree, so re-exporting generateMetadata in page.tsx isn't enough --
// without this file, /football/wc26/groups/:id fell back to the site-wide
// generic app/opengraph-image.tsx instead of the per-group standings card.
// Re-exports app/groups/[id]/opengraph-image.tsx wholesale (same trick as the
// generateMetadata re-export): that Image component reads { id } plus an
// OPTIONAL { comp }, so the wider param shape here is what makes the card
// name this competition instead of whichever tournament is globally active.
// Unguarded by isWiredFootballCompetition for the same reason
// generateMetadata is left unguarded -- an OG image for an invalid comp is
// harmless, and getTournamentForRoute ignores an unknown segment.
export { default, size, contentType, alt } from "@/app/groups/[id]/opengraph-image";
