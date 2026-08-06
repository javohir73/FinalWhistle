/** The type scale's two structural rules.
 *
 *  1. cn() must treat a scale step as a SIZE, not a colour. tailwind-merge only
 *     knows Tailwind's own font-size names; without the extension in lib/utils,
 *     cn("text-label", "text-lime-deep") drops the size entirely and the element
 *     renders with no font-size class at all. That failure is invisible in
 *     review — it looks like a working class list — so it gets a test.
 *  2. Every step declared to tailwind-merge must exist in tailwind.config, and
 *     vice versa: a step in one but not the other is either a dropped size or a
 *     class that never generates.
 */
import { readFileSync } from "fs";
import { join } from "path";
import { cn } from "@/lib/utils";

const SCALE = [
  "micro", "mini", "note", "label", "meta", "body", "lead", "sub",
  "numeral", "headline", "score-sm", "score",
];

describe("cn() keeps type-scale sizes alongside colours", () => {
  it.each(SCALE)("keeps text-%s when a colour follows", (step) => {
    expect(cn(`text-${step}`, "text-lime-deep")).toBe(`text-${step} text-lime-deep`);
  });

  it("still lets a later size override an earlier one", () => {
    expect(cn("text-label", "text-body")).toBe("text-body");
    expect(cn("text-label", "text-[13px]")).toBe("text-[13px]");
  });

  it("still lets a later colour override an earlier one", () => {
    expect(cn("text-muted", "text-lime-deep")).toBe("text-lime-deep");
  });
});

describe("scale definitions stay in sync", () => {
  const config = readFileSync(join(process.cwd(), "tailwind.config.ts"), "utf8");
  const utils = readFileSync(join(process.cwd(), "lib/utils.ts"), "utf8");

  it.each(SCALE)("tailwind.config defines %s", (step) => {
    const key = step.includes("-") ? `"${step}"` : step;
    expect(config).toMatch(new RegExp(`${key}:\\s*"\\d`));
  });

  it.each(SCALE)("lib/utils declares %s to tailwind-merge", (step) => {
    expect(utils).toContain(`"${step}"`);
  });
});

describe("no new arbitrary sizes creep back in", () => {
  it("the scale covers the sub-14px range so text-[Npx] is unnecessary", () => {
    // Not a blanket ban — a genuinely one-off size can still be arbitrary — but
    // the common steps must come from the scale. This is the check that would
    // have flagged the 225 scattered literals this scale replaced.
    const config = readFileSync(join(process.cwd(), "tailwind.config.ts"), "utf8");
    for (const px of ["8px", "9px", "10px", "11px", "12px", "13px", "15px", "17px"]) {
      expect(config).toContain(`"${px}"`);
    }
  });
});
