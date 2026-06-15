import { cn } from "@/lib/utils";

/** The FinalWhistle hexagon-whistle mark. Single-color: inherits `currentColor`
 *  (set color with a `text-*` utility). Decorative by default — give the parent
 *  (e.g. the nav link) the accessible name. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 172 156" fill="none" className={className} aria-hidden="true">
      <path
        d="M46 0h80l46 78-46 78H46L0 78 46 0Z"
        fill="none"
        stroke="currentColor"
        strokeWidth={9}
        strokeLinejoin="round"
      />
      <g transform="translate(36 44)" fill="currentColor">
        <path d="M40 70c-20.4 0-37-15.4-37-34.4C3 16.6 19.6 1.2 40 1.2c13.5 0 25.3 6.8 31.7 17h37.7c8.1 0 14.6 6.3 14.6 14.1v23.9H91.5V40.1H76.4C74 57 58.6 70 40 70Z" />
        <path d="M111.5 19h27.8c8 0 14.5 6.3 14.5 14.1v13.2h-29.9v-14c0-7.3-5.4-13.3-12.4-13.3Z" />
      </g>
    </svg>
  );
}

/** FinalWhistle wordmark with the brand two-tone split: "Final" in the
 *  foreground color, "Whistle" in lime. Mirrors APP_NAME ("FinalWhistle"). */
export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={cn("font-display tracking-tight", className)}>
      <span className="text-foreground">Final</span>
      <span className="text-win">Whistle</span>
    </span>
  );
}
