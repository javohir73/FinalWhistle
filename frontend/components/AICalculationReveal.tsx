"use client";

import { useEffect, useRef, useState } from "react";
import { Flag } from "@/components/Flag";

const STAGES = [
  "Reading group fixtures…",
  "Simulating match outcomes…",
  "Comparing team strengths…",
  "Building your prediction view…",
];

const SIGNALS = ["Elo rating", "Recent form", "Group odds", "Knockout path"];

/**
 * A short, honest "preparing your AI forecast" reveal. The forecast is already
 * precomputed server-side — this is a presentation animation, not a live model
 * run, so the copy says "preparing"/"building", never "generating live".
 * Runs ~3.4s (shortened for prefers-reduced-motion), then calls onComplete once.
 */
export function AICalculationReveal({
  team,
  onComplete,
}: {
  team: string;
  onComplete: () => void;
}) {
  const [progress, setProgress] = useState(0);
  const done = useRef(false);

  useEffect(() => {
    const reduce =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const duration = reduce ? 900 : 3400;
    const step = 60; // ms per tick

    const id = setInterval(() => {
      setProgress((p) => Math.min(100, p + (100 * step) / duration));
    }, step);

    const finish = setTimeout(() => {
      if (done.current) return;
      done.current = true;
      onComplete();
    }, duration + 120);

    return () => {
      clearInterval(id);
      clearTimeout(finish);
    };
  }, [onComplete]);

  const stageIdx = Math.min(STAGES.length - 1, Math.floor((progress / 100) * STAGES.length));
  const ready = progress >= 100;

  return (
    <section
      className="mx-auto flex max-w-lg flex-col items-center py-20 text-center sm:py-28"
      role="status"
      aria-live="polite"
      aria-label="Preparing your AI forecast"
    >
      <div className="relative grid place-items-center">
        <span
          className="absolute inset-0 -m-4 rounded-full bg-win/10 blur-xl"
          style={{ opacity: 0.4 + (progress / 100) * 0.6 }}
          aria-hidden
        />
        <span className="float relative grid place-items-center rounded-full bg-win/10 p-3 ring-1 ring-win/30">
          <Flag team={team} size={92} />
        </span>
      </div>

      <h2 className="mt-8 font-display text-2xl font-extrabold tracking-tight sm:text-3xl">
        {ready ? "Prediction ready" : "Preparing your AI forecast"}
      </h2>
      <p className="mt-2 h-6 text-muted transition-all" aria-hidden>
        {ready ? `${team}’s outlook is ready.` : STAGES[stageIdx]}
      </p>

      {/* Progress bar */}
      <div className="mt-7 h-2 w-full overflow-hidden rounded-full bg-surface-2">
        <div
          className="h-full rounded-full bg-win transition-[width] duration-100 ease-linear"
          style={{ width: `${progress}%` }}
        />
      </div>

      {/* Model signal bars filling as the forecast assembles */}
      <ul className="mt-7 grid w-full grid-cols-2 gap-3">
        {SIGNALS.map((s, i) => {
          // Each signal fills over its own slice of the timeline.
          const start = (i / SIGNALS.length) * 100;
          const fill = Math.max(0, Math.min(100, ((progress - start) / (100 / SIGNALS.length)) * 100));
          return (
            <li key={s} className="text-left">
              <div className="mb-1 flex items-center justify-between text-[11px] font-medium text-muted">
                <span>{s}</span>
                <span className="tabular-nums">{Math.round(fill)}%</span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-surface-2">
                <div
                  className="h-full rounded-full bg-win/70 transition-[width] duration-100 ease-linear"
                  style={{ width: `${fill}%` }}
                />
              </div>
            </li>
          );
        })}
      </ul>

      <p className="mt-8 text-xs text-muted/70">
        Forecasts are precomputed from 49,000 historical results — this is your view being assembled.
      </p>
    </section>
  );
}
