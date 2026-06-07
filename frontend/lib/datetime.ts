/** Timezone-aware formatting for match kickoffs. All inputs are UTC ISO strings
 *  from the API; everything is rendered in the user's chosen IANA timezone. */

function parts(iso: string, tz: string): Record<string, string> {
  const dtf = new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    weekday: "short",
  });
  const out: Record<string, string> = {};
  for (const p of dtf.formatToParts(new Date(iso))) out[p.type] = p.value;
  return out;
}

/** Stable sortable key for the local calendar day, e.g. "2026-06-11". */
export function dayKey(iso: string, tz: string): string {
  const p = parts(iso, tz);
  return `${p.year}-${p.month}-${p.day}`;
}

/** Human day heading in the user's timezone, e.g. "Thursday, 11 June 2026". */
export function dayHeading(iso: string, tz: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: tz,
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(new Date(iso));
}

/** Kickoff clock time in the user's timezone, e.g. "8:00 PM". */
export function kickoffTime(iso: string, tz: string): string {
  return new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  }).format(new Date(iso));
}

/** Short timezone abbreviation for the instant, e.g. "EDT", "BST", "GMT+9". */
export function tzAbbrev(iso: string, tz: string): string {
  const p = new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    timeZoneName: "short",
    hour: "numeric",
  }).formatToParts(new Date(iso));
  return p.find((x) => x.type === "timeZoneName")?.value ?? "";
}

/** Friendly label for a timezone id, e.g. "America/New_York" -> "New York". */
export function tzCityLabel(tz: string): string {
  const tail = tz.split("/").pop() ?? tz;
  return tail.replace(/_/g, " ");
}
