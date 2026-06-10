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

// Heights (%) of the Siri-style equalizer bars; the CSS animation morphs them.
const WAVE = [38, 64, 92, 70, 100, 58, 86, 48, 30];

/**
 * A short, honest "preparing your AI forecast" reveal styled as a Siri/Jarvis
 * thinking orb — rotating HUD rings, a radar sweep, a breathing halo and an
 * audio-style waveform — so it clearly reads as "the AI is working". The
 * forecast is precomputed server-side, so the copy says "preparing"/"building",
 * never "generating live". Runs ~3.4s (shortened for prefers-reduced-motion),
 * then calls onComplete once.
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
      className="mx-auto flex max-w-lg flex-col items-center py-16 text-center sm:py-24"
      role="status"
      aria-live="polite"
      aria-label="Preparing your AI forecast"
    >
      {/* ===== Thinking orb ===== */}
      <div className="relative grid h-56 w-56 place-items-center sm:h-64 sm:w-64">
        {/* Breathing halo, intensifies with progress */}
        <span
          aria-hidden
          className="ai-pulse absolute inset-2 rounded-full bg-win/25 blur-2xl"
          style={{ opacity: 0.3 + (progress / 100) * 0.55 }}
        />

        {/* Radar sweep (a soft arc orbiting the rim) */}
        <span
          aria-hidden
          className="ai-sweep absolute inset-0 rounded-full"
          style={{
            background:
              "conic-gradient(from 0deg, transparent 0deg 250deg, hsl(var(--win) / 0.05) 300deg, hsl(var(--win) / 0.6) 352deg, transparent 360deg)",
            WebkitMask:
              "radial-gradient(farthest-side, transparent calc(100% - 16px), #000 calc(100% - 15px))",
            mask: "radial-gradient(farthest-side, transparent calc(100% - 16px), #000 calc(100% - 15px))",
          }}
        />

        {/* HUD rings — each layer rotates independently */}
        <span aria-hidden className="ai-spin-cw absolute inset-0">
          <svg viewBox="0 0 200 200" className="h-full w-full text-win" fill="none">
            <circle cx="100" cy="100" r="95" stroke="currentColor" strokeOpacity="0.14" strokeWidth="1" />
            <circle
              cx="100" cy="100" r="86"
              stroke="currentColor" strokeOpacity="0.4" strokeWidth="1.5"
              strokeDasharray="2 12" strokeLinecap="round"
            />
          </svg>
        </span>
        <span aria-hidden className="ai-spin-ccw absolute inset-0">
          <svg viewBox="0 0 200 200" className="h-full w-full text-win" fill="none">
            {/* Two bright arcs, like a targeting reticle */}
            <circle
              cx="100" cy="100" r="74"
              stroke="currentColor" strokeOpacity="0.65" strokeWidth="2.5"
              strokeDasharray="46 187" strokeLinecap="round"
            />
            <circle
              cx="100" cy="100" r="74"
              stroke="currentColor" strokeOpacity="0.65" strokeWidth="2.5"
              strokeDasharray="46 187" strokeDashoffset="-117" strokeLinecap="round"
            />
          </svg>
        </span>
        <span aria-hidden className="ai-spin-cw-fast absolute inset-0">
          <svg viewBox="0 0 200 200" className="h-full w-full text-win" fill="none">
            <circle cx="100" cy="100" r="62" stroke="currentColor" strokeOpacity="0.22" strokeWidth="1" strokeDasharray="1 7" />
          </svg>
        </span>

        {/* Core — the flag in a glowing disc */}
        <span className="relative grid place-items-center rounded-full bg-surface/85 p-3 ring-1 ring-win/40 shadow-[0_0_36px_-6px_hsl(var(--win)/0.7)]">
          <Flag team={team} size={80} />
        </span>
      </div>

      {/* ===== Siri waveform ===== */}
      <div
        aria-hidden
        className="mt-6 flex h-9 items-end justify-center gap-[5px] transition-opacity duration-500"
        style={{ opacity: ready ? 0.25 : 1 }}
      >
        {WAVE.map((h, i) => (
          <span
            key={i}
            className="ai-eq w-1 rounded-full bg-win"
            style={{
              height: `${h}%`,
              animationDelay: `${i * 90}ms`,
              animationDuration: `${720 + (i % 3) * 160}ms`,
            }}
          />
        ))}
      </div>

      <h2 className="mt-6 font-display text-2xl font-extrabold tracking-tight sm:text-3xl">
        {ready ? "Prediction ready" : "Preparing your AI forecast"}
      </h2>
      <p className="mt-2 h-6 text-muted" aria-hidden>
        {ready ? `${team}’s outlook is ready.` : STAGES[stageIdx]}
      </p>

      {/* Progress bar */}
      <div className="mt-6 h-2 w-full overflow-hidden rounded-full bg-surface-2">
        <div
          className="h-full rounded-full bg-win transition-[width] duration-100 ease-linear"
          style={{ width: `${progress}%` }}
        />
      </div>

      {/* Model signal bars filling as the forecast assembles */}
      <ul className="mt-7 grid w-full grid-cols-2 gap-3">
        {SIGNALS.map((s, i) => {
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
