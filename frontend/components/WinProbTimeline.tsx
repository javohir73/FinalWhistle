/** WinProbTimeline (Floodlight P4 slice p4-s1): the match centre's win-probability
 *  chart (design/Floodlight Prototype.dc.html, match-centre lines 235-245). For
 *  football this is the model's PRE-MATCH forecast trajectory — dated snapshots
 *  leading up to kickoff, from getProbHistory* — rendered as an honest "how the
 *  model's read shifted" line, NOT a fabricated minute-by-minute in-match chart
 *  (there is no minute field or goal-event alignment in that payload). Goal/event
 *  markers are supported structurally (optional `markers`) for NRL reuse later;
 *  football passes none.
 *
 *  Deterministic server component: no "use client", no window/hooks, so it renders
 *  identical markup server- and client-side. When there are <2 points there is no
 *  trajectory to draw, so it degrades to the pre-match hero bar (the plan's honest
 *  single-bar state) — never a fake chart.
 */
import type { ProbHistoryPoint, Probabilities } from "@/lib/types";
import { ProbabilityBar } from "@/components/ProbabilityBar";
import { Eyebrow } from "@/components/Eyebrow";
import { pct } from "@/lib/format";
import { cn } from "@/lib/utils";

interface Props {
  points: ProbHistoryPoint[];
  probabilities: Probabilities;
  homeLabel: string;
  awayLabel: string;
  /** Optional event markers (NRL reuse): `at` is a 0..1 fractional x position,
   *  `tone` picks the ring color. Football passes none. */
  markers?: { at: number; tone: "home" | "away" }[];
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Compact "D MMM" from an ISO-ish date string, by string-parsing the YYYY-MM-DD
 *  prefix so the label stays byte-deterministic (no Intl/tz dependence in this
 *  pure server component). Null for anything that doesn't parse. */
function shortDate(iso: string | null): string | null {
  const m = iso ? /^(\d{4})-(\d{2})-(\d{2})/.exec(iso) : null;
  if (!m) return null;
  const month = MONTHS[Number(m[2]) - 1];
  return month ? `${Number(m[3])} ${month}` : null;
}

/** Round to 2dp so the emitted SVG coordinates stay short and deterministic. */
const r2 = (v: number) => Math.round(v * 100) / 100;

export function WinProbTimeline({ points, probabilities, homeLabel, awayLabel, markers = [] }: Props) {
  // Honest fallback: no trajectory to draw yet (most fixtures until the model
  // starts updating them), so show only the pre-match hero bar — not a chart.
  if (points.length < 2) {
    return (
      <div>
        <Eyebrow tone="muted">MODEL FORECAST</Eyebrow>
        <div className="mt-3">
          <ProbabilityBar
            probabilities={probabilities}
            homeLabel={homeLabel}
            awayLabel={awayLabel}
            size="hero"
            showLabels
          />
        </div>
        <p className="mt-2 text-[13px] text-muted">
          Forecast movement appears once the model updates this fixture.
        </p>
      </div>
    );
  }

  const series = points.map((p) => p.p_home);
  const n = series.length;
  const first = series[0];
  const last = series[n - 1];

  // Prototype geometry: viewBox 354x80, home 100% -> y 0 (top), home 0% -> y 80.
  const xFor = (i: number) => (i / (n - 1)) * 354;
  const yFor = (p: number) => (1 - p) * 80;
  // Linear interpolation of y at a fractional x (0..1) — markers sit on the path.
  const interpY = (at: number) => {
    const posn = Math.min(Math.max(at, 0), 1) * (n - 1);
    const i0 = Math.floor(posn);
    const i1 = Math.min(i0 + 1, n - 1);
    const t = posn - i0;
    return yFor(series[i0] + (series[i1] - series[i0]) * t);
  };

  const d = series.map((p, i) => `${i === 0 ? "M" : "L"}${r2(xFor(i))} ${r2(yFor(p))}`).join(" ");

  // Axis labels: honest steps, never fabricated KO/1H/HT/2H minutes. Dated
  // snapshots print first/mid dates ending at kickoff; undated fall to EARLIER…NOW.
  const dated = points.some((p) => p.date);
  const axisLabels = dated
    ? [
        shortDate(points[0].date) ?? "EARLIER",
        shortDate(points[Math.floor((n - 1) / 2)].date) ?? "",
        "KO",
      ]
    : ["EARLIER", "NOW"];

  // The text alternative (aria-label + <svg> <title>): names the printed current
  // % and direction so the visual is never color-alone.
  const label = `Model forecast for ${homeLabel}: moved from ${pct(first)} to ${pct(last)} across ${n} updates`;

  return (
    <div>
      <div className="flex justify-between">
        <Eyebrow tone="muted">WIN PROBABILITY · FORECAST</Eyebrow>
        <span className="text-[11px] font-semibold tabular-nums text-lime-deep">
          {homeLabel} {pct(last)}
        </span>
      </div>

      <svg
        role="img"
        aria-label={label}
        viewBox="0 0 354 80"
        preserveAspectRatio="none"
        width="100%"
        height="80"
        className="mt-2.5"
      >
        <title>{label}</title>
        {/* 50% reference baseline. */}
        <line
          x1={0}
          y1={40}
          x2={354}
          y2={40}
          strokeWidth={1}
          strokeDasharray="3 3"
          className="[stroke:hsl(var(--border))]"
        />
        {/* The forecast trajectory. */}
        <path
          d={d}
          fill="none"
          strokeWidth={2.5}
          strokeLinejoin="round"
          strokeLinecap="round"
          className="stroke-lime-deep"
        />
        {/* Optional event markers (NRL reuse; football passes none). */}
        {markers.map((mk, i) => (
          <circle
            key={i}
            cx={r2(mk.at * 354)}
            cy={r2(interpY(mk.at))}
            r={4}
            strokeWidth={2}
            className={cn(
              "[fill:hsl(var(--surface))]",
              mk.tone === "home" ? "stroke-lime-deep" : "stroke-loss",
            )}
          />
        ))}
        {/* Current (last) point. */}
        <circle cx={354} cy={r2(yFor(last))} r={3.5} className="fill-lime-deep" />
      </svg>

      <div className="flex justify-between text-[11px] text-muted">
        {axisLabels.map((t, i) => (
          <span key={i}>{t}</span>
        ))}
      </div>
    </div>
  );
}
