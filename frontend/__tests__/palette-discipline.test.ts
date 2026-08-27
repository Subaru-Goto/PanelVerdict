import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

// 056/#151 adopted a given palette — three inks, a rule, two surfaces, and
// three colours reserved for state. Nine names, all in `globals.css`. The
// failure this guards is not a wrong colour, it is the slow return of the
// arrangement it replaced: 1,020 lines of components each reaching for
// whichever Tailwind swatch looked right, with no shared vocabulary. One
// `text-zinc-500` is invisible in review; fifty of them are the old app back.
//
// Derived from the tree, not a list, so a new component is covered the day it
// appears.

const APP_DIR = join(__dirname, "..", "app");

const TAILWIND_SCALE =
  "slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|" +
  "teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose";

// A numbered swatch — `text-zinc-500`, `fill-blue-600/25`. The palette's own
// names carry no number (`text-ink-2` is a token, `text-red` is a state), so
// requiring the digits is what keeps this from firing on the vocabulary it
// exists to protect.
const OFF_PALETTE = new RegExp(
  `\\b(?:[a-z-]+:)*(?:text|bg|border|fill|stroke|outline|ring|divide|from|via|to|decoration|accent|caret|shadow)-(?:${TAILWIND_SCALE})-\\d{2,3}\\b`,
  "g",
);

// The palette has one mode. A `dark:` utility is a colour no design decided,
// and the pair it belongs to cannot be checked against a design that has no
// dark half.
const DARK_VARIANT = /\bdark:/g;

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true, recursive: true })
    .filter((e) => e.isFile() && /\.tsx?$/.test(e.name))
    .map((e) => join(e.parentPath, e.name));
}

function offences(pattern: RegExp): string[] {
  return sourceFiles(APP_DIR).flatMap((file) => {
    const found = readFileSync(file, "utf8").match(pattern) ?? [];
    return found.map((hit) => `${relative(APP_DIR, file)}: ${hit}`);
  });
}

describe("the palette's discipline", () => {
  it("names only colours the design decided", () => {
    expect(offences(OFF_PALETTE)).toEqual([]);
  });

  it("carries no dark-mode variant", () => {
    expect(offences(DARK_VARIANT)).toEqual([]);
  });
});
