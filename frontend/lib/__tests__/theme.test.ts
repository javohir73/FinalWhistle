/** Theme preference + the Daylight token set's accessibility floor. */
import {
  DEFAULT_THEME, LIGHT_CLASS, THEME_KEY, applyTheme, isTheme, readTheme,
  resolveTheme, writeTheme,
} from "@/lib/theme";
import { readFileSync } from "fs";
import { join } from "path";

afterEach(() => {
  window.localStorage.clear();
  document.documentElement.className = "";
});

describe("preference storage", () => {
  it("defaults to dark — light is opt-in, never inferred from the OS", () => {
    // Following prefers-color-scheme would flip most visitors to light, since
    // most systems report light unless changed. That is a brand decision, not
    // a default.
    expect(DEFAULT_THEME).toBe("dark");
    expect(readTheme()).toBeNull();
    expect(resolveTheme()).toBe("dark");
  });

  it("round-trips a stored choice", () => {
    writeTheme("light");
    expect(window.localStorage.getItem(THEME_KEY)).toBe("light");
    expect(readTheme()).toBe("light");
    expect(resolveTheme()).toBe("light");
  });

  it("ignores a corrupt stored value rather than applying it", () => {
    window.localStorage.setItem(THEME_KEY, "neon");
    expect(readTheme()).toBeNull();
    expect(resolveTheme()).toBe("dark");
  });

  it("survives storage that throws (Safari private mode)", () => {
    const spy = jest.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    expect(() => readTheme()).not.toThrow();
    expect(readTheme()).toBeNull();
    spy.mockRestore();
    const setSpy = jest.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    expect(() => writeTheme("light")).not.toThrow();
    setSpy.mockRestore();
  });

  it("guards the type", () => {
    expect(isTheme("dark")).toBe(true);
    expect(isTheme("light")).toBe(true);
    expect(isTheme("sepia")).toBe(false);
  });
});

describe("applyTheme", () => {
  it("adds and removes the daylight class", () => {
    applyTheme("light");
    expect(document.documentElement.classList.contains(LIGHT_CLASS)).toBe(true);
    applyTheme("dark");
    expect(document.documentElement.classList.contains(LIGHT_CLASS)).toBe(false);
  });

  it("moves the browser-chrome colour with the theme", () => {
    const meta = document.createElement("meta");
    meta.setAttribute("name", "theme-color");
    meta.setAttribute("content", "#0a1410");
    document.head.appendChild(meta);
    applyTheme("light");
    expect(meta.getAttribute("content")).toBe("#f2f6ef");
    applyTheme("dark");
    expect(meta.getAttribute("content")).toBe("#0a1410");
    meta.remove();
  });
});

describe("no flash of the wrong theme", () => {
  const layout = readFileSync(join(process.cwd(), "app/layout.tsx"), "utf8");

  it("applies the stored theme from an inline script in <head>", () => {
    // React cannot do this: by the time it hydrates the wrong theme has been
    // painted. The script must be inline and synchronous.
    expect(layout).toContain("dangerouslySetInnerHTML");
    expect(layout).toContain(THEME_KEY);
    expect(layout).toContain(LIGHT_CLASS);
  });

  it("boots before the render tree, not after", () => {
    expect(layout.indexOf(THEME_KEY)).toBeLessThan(layout.indexOf("<body"));
  });
});

describe("Daylight meets WCAG AA", () => {
  const css = readFileSync(join(process.cwd(), "app/globals.css"), "utf8");
  const daylight = css.slice(css.indexOf(".theme-daylight {"));

  const rgb = (h: number, s: number, l: number) => {
    const c = (1 - Math.abs(2 * l - 1)) * s;
    const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
    const m = l - c / 2;
    const [r, g, b] = h >= 120 && h < 180 ? [0, c, x] : [c, x, 0];
    return [r + m, g + m, b + m].map((v) => v * 255);
  };
  const lum = ([r, g, b]: number[]) => {
    const f = (v: number) => {
      v /= 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const ratio = (a: number[], b: number[]) => {
    const [hi, lo] = [lum(a), lum(b)].sort((m, n) => n - m);
    return (hi + 0.05) / (lo + 0.05);
  };

  it("keeps muted body text above the 4.5:1 floor on canvas and card", () => {
    // It shipped at 140 7% 45% = 4.14:1 on the canvas — under AA, on the token
    // that carries most secondary copy.
    const m = daylight.match(/--muted:\s*([\d.]+) ([\d.]+)% ([\d.]+)%/);
    expect(m).not.toBeNull();
    const muted = rgb(Number(m![1]), Number(m![2]) / 100, Number(m![3]) / 100);
    const canvas = rgb(96, 0.23, 0.96);
    expect(ratio(muted, canvas)).toBeGreaterThanOrEqual(4.5);
    expect(ratio(muted, [255, 255, 255])).toBeGreaterThanOrEqual(4.5);
  });

  it("keeps primary ink far above the floor", () => {
    const m = daylight.match(/--foreground:\s*([\d.]+) ([\d.]+)% ([\d.]+)%/)!;
    const fg = rgb(Number(m[1]), Number(m[2]) / 100, Number(m[3]) / 100);
    expect(ratio(fg, rgb(96, 0.23, 0.96))).toBeGreaterThanOrEqual(7); // AAA
  });
});
