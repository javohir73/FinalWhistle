import type { Config } from "tailwindcss";

// "Daylight" light design system. Color tokens are CSS variables (see globals.css).
const config: Config = {
  darkMode: ["class"],
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        border: "hsl(var(--border))",
        background: "hsl(var(--background))",
        surface: "hsl(var(--surface))",
        "surface-2": "hsl(var(--surface-2))",
        foreground: "hsl(var(--foreground))",
        muted: "hsl(var(--muted))",
        win: "hsl(var(--win))",
        draw: "hsl(var(--draw))",
        loss: "hsl(var(--loss))",
        gold: "hsl(var(--gold))",
        accent: "hsl(var(--accent))",
        "lime-deep": "hsl(var(--lime-deep))",
        "amber-ink": "hsl(var(--amber-ink))",
        pitch: "hsl(var(--pitch))",
      },
      fontFamily: {
        display: ["var(--font-display)", "system-ui", "sans-serif"],
        sans: ["var(--font-body)", "system-ui", "sans-serif"],
      },
      fontSize: {
        // Floodlight (P1): display scale utility access; the .text-display-hero
        // / .text-rank component classes in globals.css already cover most consumers.
        "display-hero": "var(--text-display-hero)",
        rank: "var(--text-rank)",

        // ---- The type scale (2026-08-07) ----
        // Replaces ~225 arbitrary `text-[Npx]` literals that were scattered
        // across 79 files with names that say what the text IS. Sizes are the
        // ones already shipping, so this is a rename, not a redesign — every
        // value below is the exact px the components already rendered.
        //
        // Three half-pixel sizes (8.5/9.5/12.5) did NOT survive: they were
        // one-off nudges, not steps in a scale, and are folded into their
        // nearest whole step (4 elements move by half a pixel).
        //
        // Tailwind's own text-xs/sm/base still exist; this scale covers the
        // sub-14px range the design uses and Tailwind's default does not.
        micro: "8px", //   badge overlines, crest captions
        mini: "9px", //    dense table furniture
        note: "10px", //   secondary labels, chips
        label: "11px", //  THE workhorse — uppercase labels, meta rows
        meta: "12px", //   inline secondary copy
        body: "13px", //   readable body in dense cards
        lead: "15px", //   card lead-ins
        sub: "17px", //    sub-headings, team names in heroes
        // Display numerals — big, tabular, never body copy.
        numeral: "25px", //   scoreboard
        headline: "30px", //  feature hero
        "score-sm": "40px", // scorebug, pre-kickoff
        score: "44px", //     scorebug, live and full time
      },
      borderRadius: {
        xl: "1rem",
        "2xl": "1.25rem",
        "3xl": "1.5rem",
      },
    },
  },
  plugins: [],
};

export default config;
