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
