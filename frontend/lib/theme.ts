/** Theme preference: the Floodlight dark system (default) or Daylight.
 *
 *  Dark stays the default on purpose. This platform's identity is the dark
 *  system, and following `prefers-color-scheme` would silently flip the
 *  majority of visitors to light — most operating systems report light unless
 *  the user changed it. Light is therefore opt-in, remembered per browser.
 *
 *  Pure + SSR-safe, same shape as lib/competitionPrefs.ts: every read/write
 *  guards `window` and wraps localStorage in try/catch (Safari private mode
 *  throws on access, not just on write).
 */
export type Theme = "dark" | "light";

/** Read by the inline boot script in app/layout.tsx too — keep them in sync. */
export const THEME_KEY = "fw_theme";
/** The class globals.css hangs the Daylight token set on. */
export const LIGHT_CLASS = "theme-daylight";

export const DEFAULT_THEME: Theme = "dark";

export function isTheme(v: unknown): v is Theme {
  return v === "dark" || v === "light";
}

export function readTheme(): Theme | null {
  if (typeof window === "undefined") return null;
  try {
    const v = window.localStorage.getItem(THEME_KEY);
    return isTheme(v) ? v : null;
  } catch {
    return null; // private-mode / disabled storage
  }
}

export function writeTheme(theme: Theme): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(THEME_KEY, theme);
  } catch {
    /* ignore — the theme still applies for this session */
  }
}

/** Put the document into ``theme``. Also moves the browser-chrome colour, so
 *  mobile address bars don't stay Floodlight-dark behind a light page. */
export function applyTheme(theme: Theme): void {
  if (typeof document === "undefined") return;
  document.documentElement.classList.toggle(LIGHT_CLASS, theme === "light");
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", theme === "light" ? "#f2f6ef" : "#0a1410");
}

/** The stored choice, or the default. */
export function resolveTheme(): Theme {
  return readTheme() ?? DEFAULT_THEME;
}
