"use client";

import { useState } from "react";
import { useTimezone, detectTimezone } from "@/lib/useTimezone";
import { tzCityLabel } from "@/lib/datetime";

/** Curated list of IANA timezones grouped by region, for the change dropdown. */
const TIMEZONES: { group: string; zones: [string, string][] }[] = [
  {
    group: "Host countries",
    zones: [
      ["America/Los_Angeles", "Los Angeles / Vancouver / Seattle"],
      ["America/Denver", "Denver"],
      ["America/Chicago", "Dallas / Houston / Kansas City"],
      ["America/New_York", "New York / Toronto / Miami / Atlanta"],
      ["America/Mexico_City", "Mexico City / Guadalajara / Monterrey"],
    ],
  },
  {
    group: "Americas",
    zones: [
      ["America/Sao_Paulo", "São Paulo / Buenos Aires"],
      ["America/Bogota", "Bogotá / Lima"],
      ["America/Halifax", "Halifax"],
    ],
  },
  {
    group: "Europe & Africa",
    zones: [
      ["Europe/London", "London / Lisbon / Dublin"],
      ["Europe/Paris", "Paris / Berlin / Madrid / Rome"],
      ["Europe/Athens", "Athens / Cairo / Johannesburg"],
      ["Europe/Moscow", "Moscow / Istanbul / Riyadh"],
      ["Africa/Lagos", "Lagos / Algiers"],
    ],
  },
  {
    group: "Asia & Pacific",
    zones: [
      ["Asia/Dubai", "Dubai"],
      ["Asia/Tehran", "Tehran"],
      ["Asia/Tashkent", "Tashkent"],
      ["Asia/Karachi", "Karachi / Islamabad"],
      ["Asia/Kolkata", "Mumbai / Delhi"],
      ["Asia/Bangkok", "Bangkok / Jakarta"],
      ["Asia/Shanghai", "Beijing / Singapore"],
      ["Asia/Tokyo", "Tokyo / Seoul"],
      ["Australia/Sydney", "Sydney"],
      ["Pacific/Auckland", "Auckland"],
      ["UTC", "UTC"],
    ],
  },
];

function Select({
  value,
  onChange,
}: {
  value: string;
  onChange: (tz: string) => void;
}) {
  // Ensure the current value and the auto-detected zone are always selectable,
  // even if they aren't in the curated list.
  const inList = (id: string) => TIMEZONES.some((g) => g.zones.some(([z]) => z === id));
  const extras = [value, detectTimezone()].filter(
    (id, i, arr) => id && !inList(id) && arr.indexOf(id) === i,
  );
  return (
    <select
      id="timezone-select"
      name="timezone"
      aria-label="Choose your timezone"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="min-w-0 flex-1 rounded-lg border border-border bg-surface-2 px-2.5 py-1.5 text-sm font-medium text-foreground outline-none transition focus:border-win sm:flex-none"
    >
      {extras.length > 0 && (
        <optgroup label="Detected">
          {extras.map((id) => (
            <option key={id} value={id}>
              {tzCityLabel(id)}
            </option>
          ))}
        </optgroup>
      )}
      {TIMEZONES.map((g) => (
        <optgroup key={g.group} label={g.group}>
          {g.zones.map(([id, label]) => (
            <option key={id} value={id}>
              {label}
            </option>
          ))}
        </optgroup>
      ))}
    </select>
  );
}

/** First-visit banner that asks the user to confirm or change their location,
 *  then collapses into a compact "times shown in …" control. */
export function LocationPicker() {
  const { tz, confirmed, hydrated, setTimezone, confirm } = useTimezone();
  const [editing, setEditing] = useState(false);

  if (!hydrated) {
    // Reserve space to avoid layout shift before localStorage hydrates.
    return <div className="h-[58px]" aria-hidden />;
  }

  if (!confirmed) {
    return (
      <div className="glass flex flex-col gap-3 rounded-xl px-4 py-3.5 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2.5 text-sm">
          <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-win/15 text-lime-deep">
            <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 21s-7-5.2-7-11a7 7 0 1 1 14 0c0 5.8-7 11-7 11Z" strokeLinejoin="round" />
              <circle cx="12" cy="10" r="2.5" />
            </svg>
          </span>
          <span className="text-muted">
            Kickoff times in your local time —{" "}
            <span className="font-semibold text-foreground">{tzCityLabel(tz)}</span>. Not right?
          </span>
        </div>
        <div className="flex w-full items-center gap-2 sm:w-auto">
          <Select value={tz} onChange={setTimezone} />
          <button
            onClick={confirm}
            className="shrink-0 rounded-lg bg-win px-3.5 py-1.5 text-sm font-display font-bold text-pitch transition hover:brightness-110"
          >
            Use this
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2 text-sm text-muted">
      <svg viewBox="0 0 24 24" className="h-4 w-4 text-lime-deep" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M12 21s-7-5.2-7-11a7 7 0 1 1 14 0c0 5.8-7 11-7 11Z" strokeLinejoin="round" />
        <circle cx="12" cy="10" r="2.5" />
      </svg>
      {editing ? (
        <Select
          value={tz}
          onChange={(t) => {
            setTimezone(t);
            setEditing(false);
          }}
        />
      ) : (
        <>
          <span>
            Times in{" "}
            <span className="font-semibold text-foreground">{tzCityLabel(tz)}</span>
          </span>
          <button
            onClick={() => setEditing(true)}
            className="rounded-md px-2 py-0.5 text-xs font-medium text-lime-deep underline-offset-2 transition hover:bg-win/10 hover:underline"
          >
            Change
          </button>
        </>
      )}
    </div>
  );
}
