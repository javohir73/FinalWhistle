// Floodlight P1 slice p1-s3: colocates the OG image convention file for this
// segment. Next resolves opengraph-image by walking the *matched route's own*
// segment tree, so re-exporting generateMetadata in page.tsx isn't enough --
// without this file, /football/wc26/match/:id fell back to the site-wide
// generic app/opengraph-image.tsx instead of the per-match flags +
// prediction-% card. Re-exports app/match/[id]/opengraph-image.tsx wholesale
// (same trick as the generateMetadata re-export): its Image component only
// destructures { id } off params, so the wider { comp, id } param shape here
// passes straight through untouched. Unguarded by isWiredFootballCompetition
// for the same reason generateMetadata is left unguarded -- an OG image for
// an invalid comp is harmless.
export { default, size, contentType, alt } from "@/app/match/[id]/opengraph-image";
