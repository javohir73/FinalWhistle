import Link from "next/link";
import { Parallax } from "@/components/Parallax";
import { Reveal } from "@/components/Reveal";
import { SoccerBall, PitchLines, Player } from "@/components/illustrations";

export default function IntroPage() {
  return (
    <div className="-mt-8">
      {/* ===================== HERO ===================== */}
      <section className="relative overflow-hidden">
        {/* Parallax pitch backdrop */}
        <Parallax speed={70} className="pointer-events-none absolute inset-x-0 -top-10 z-0 flex justify-center">
          <PitchLines className="w-[120%] max-w-5xl opacity-[0.18]" />
        </Parallax>

        {/* Floating ball, top-right */}
        <Parallax speed={120} rotate={40} className="pointer-events-none absolute right-[6%] top-10 z-0 hidden sm:block">
          <div className="float">
            <SoccerBall className="h-24 w-24 drop-shadow-[0_10px_30px_rgba(0,0,0,0.5)]" />
          </div>
        </Parallax>

        {/* Small ball, lower-left */}
        <Parallax speed={-90} rotate={-30} className="pointer-events-none absolute left-[4%] top-72 z-0 hidden md:block">
          <div className="float-slow">
            <SoccerBall className="h-12 w-12 opacity-90" />
          </div>
        </Parallax>

        {/* Player silhouettes */}
        <Parallax speed={150} className="pointer-events-none absolute right-[14%] top-56 z-0 hidden lg:block text-win/20">
          <Player variant="kick" className="h-44 w-44" />
        </Parallax>
        <Parallax speed={90} className="pointer-events-none absolute left-[10%] top-24 z-0 hidden lg:block text-foreground/10">
          <Player variant="run" className="h-36 w-36 -scale-x-100" />
        </Parallax>

        <div className="relative z-10 mx-auto max-w-3xl py-28 text-center sm:py-36">
          <div className="mb-5 inline-flex items-center gap-2 rounded-full chip px-3 py-1 text-xs font-medium text-muted">
            <span className="h-1.5 w-1.5 rounded-full bg-win shadow-[0_0_8px_hsl(var(--win))]" />
            FIFA World Cup 2026 · USA · Canada · Mexico
          </div>
          <h1 className="font-display text-5xl font-extrabold leading-[1.02] tracking-tight sm:text-7xl">
            Every match,
            <br />
            <span className="text-gradient">predicted &amp; explained.</span>
          </h1>
          <p className="mx-auto mt-6 max-w-xl text-lg text-muted">
            FinalWhistle turns 49,000 historical results into calibrated AI forecasts
            for all 104 fixtures — win probabilities, scorelines, and the reasoning
            behind every call.
          </p>
          <div className="mt-9 flex flex-wrap justify-center gap-3">
            <Link
              href="/matches"
              className="rounded-xl bg-win px-6 py-3 font-display font-bold text-background transition hover:brightness-110"
            >
              View predictions →
            </Link>
            <Link
              href="/brackets"
              className="rounded-xl border border-border bg-surface/60 px-6 py-3 font-display font-semibold text-foreground transition hover:border-win/40"
            >
              Road to the Final
            </Link>
          </div>
        </div>
      </section>

      {/* ===================== STATS ===================== */}
      <Reveal>
        <section className="grid grid-cols-2 gap-4 border-y border-border/60 py-10 sm:grid-cols-4">
          {[
            ["48", "Teams"],
            ["104", "Matches"],
            ["49k", "Results trained on"],
            ["1872", "History since"],
          ].map(([n, l]) => (
            <div key={l} className="text-center">
              <div className="font-display text-4xl font-extrabold text-win">{n}</div>
              <div className="mt-1 text-xs uppercase tracking-wider text-muted">{l}</div>
            </div>
          ))}
        </section>
      </Reveal>

      {/* ===================== FEATURES ===================== */}
      <section className="space-y-24 py-24">
        {FEATURES.map((f, i) => (
          <Reveal key={f.title}>
            <div
              className={`flex flex-col items-center gap-10 md:flex-row ${
                i % 2 ? "md:flex-row-reverse" : ""
              }`}
            >
              <div className="flex-1">
                <span className="font-display text-sm font-bold uppercase tracking-[0.2em] text-win">
                  0{i + 1}
                </span>
                <h2 className="mt-2 font-display text-3xl font-extrabold tracking-tight sm:text-4xl">
                  {f.title}
                </h2>
                <p className="mt-3 max-w-md text-muted">{f.body}</p>
              </div>
              <div className="relative flex flex-1 justify-center">
                <Parallax speed={50} rotate={i % 2 ? -12 : 12}>
                  <div className="glass grid h-56 w-56 place-items-center rounded-3xl">
                    {f.art}
                  </div>
                </Parallax>
              </div>
            </div>
          </Reveal>
        ))}
      </section>

      {/* ===================== FINAL CTA ===================== */}
      <Reveal>
        <section className="relative mb-10 overflow-hidden rounded-3xl glass px-6 py-16 text-center">
          <Parallax speed={60} rotate={30} className="pointer-events-none absolute -right-6 -top-6 opacity-80">
            <div className="spin-slow"><SoccerBall className="h-28 w-28" /></div>
          </Parallax>
          <h2 className="font-display text-3xl font-extrabold tracking-tight sm:text-5xl">
            Who lifts the trophy?
          </h2>
          <p className="mx-auto mt-3 max-w-md text-muted">
            Explore live predictions, group odds, and the projected road to the final.
          </p>
          <Link
            href="/matches"
            className="mt-7 inline-block rounded-xl bg-win px-7 py-3 font-display font-bold text-background transition hover:brightness-110"
          >
            Explore predictions →
          </Link>
        </section>
      </Reveal>
    </div>
  );
}

const FEATURES = [
  {
    title: "Calibrated probabilities",
    body: "A stated 60% means it happens about 60% of the time — back-tested against the 2018 and 2022 World Cups and tuned to beat naive baselines.",
    art: <Player variant="run" className="h-32 w-32 text-win" />,
  },
  {
    title: "Explained, not black-box",
    body: "Every prediction shows the factors that drove it — Elo gap, recent form, head-to-head, and host advantage — in plain language.",
    art: <PitchLines className="w-44" />,
  },
  {
    title: "From group to final",
    body: "Monte-Carlo simulated group tables, qualification odds, and a projected knockout picture across all 48 nations.",
    art: <SoccerBall className="h-28 w-28 spin-slow" />,
  },
];
