/** The theme system's one structural rule: every colour a surface paints with
 *  must come from a token, so swapping :root for .theme-daylight re-themes the
 *  whole UI. A literal baked into a gradient does not switch — .glass shipped
 *  with a hardcoded near-black foot, and under daylight every card faded to
 *  black with unreadable text at the bottom. These read the stylesheet as text
 *  (jsdom applies no Tailwind/PostCSS) and fail if that class of orphan
 *  returns. */
import { readFileSync } from "fs";
import { join } from "path";

const css = readFileSync(join(process.cwd(), "app/globals.css"), "utf8");

function block(selector: string): string {
  const start = css.indexOf(selector);
  if (start === -1) throw new Error(`${selector} not found in globals.css`);
  return css.slice(start, css.indexOf("}", start));
}

it("paints the card gradient from tokens, never a baked literal", () => {
  const glass = block(".glass {");
  expect(glass).toContain("hsl(var(--surface))");
  expect(glass).toContain("hsl(var(--surface-grad-end))");
  // No raw hsl(<numbers>) triple anywhere in the rule.
  expect(glass).not.toMatch(/hsl\(\s*\d/);
});

it("defines the card gradient foot in BOTH themes", () => {
  expect(block(":root {")).toMatch(/--surface-grad-end:\s*148 29% 8%/);
  expect(block(".theme-daylight {")).toMatch(/--surface-grad-end:\s*\d/);
});

it("keeps the dark value byte-identical to the literal it replaced", () => {
  // The refactor must be a pure rename: dark rendering cannot shift by a hair.
  expect(block(":root {")).toContain("--surface-grad-end: 148 29% 8%");
});

it("gives daylight a LIGHT gradient foot, not an inherited dark one", () => {
  const m = block(".theme-daylight {").match(/--surface-grad-end:\s*[\d.]+ [\d.]+% ([\d.]+)%/);
  expect(m).not.toBeNull();
  expect(Number(m![1])).toBeGreaterThan(50); // lightness, not a near-black
});
