// Floodlight P6: the canonical /football/<comp>/match/<id> URL wraps the legacy
// match centre (see page.tsx). The match page's five parallel fetches are the
// highest cold-start risk, so this canonical URL reuses the same skeleton.
export { default } from "@/app/match/[id]/loading";
