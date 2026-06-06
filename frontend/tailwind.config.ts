import type { Config } from "tailwindcss";

// Tailwind config. The CSS-variable color tokens below are the shadcn/ui
// convention, so shadcn components can be added later (task 6) without rework.
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
        foreground: "hsl(var(--foreground))",
        // Outcome colors used by the W/D/L probability bar.
        win: "hsl(var(--win))",
        draw: "hsl(var(--draw))",
        loss: "hsl(var(--loss))",
      },
    },
  },
  plugins: [],
};

export default config;
