import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import {
  AI_SYSTEM_DISCLOSURE,
  ANALYST_DISCLOSURE,
} from "../app/lib/disclosure";

// The components have their own disclosure tests. This one watches the settled
// design instead, because that is the copy nobody runs: the drawing had lost
// both sentences, and building it as drawn would have deleted them (098/#207).
//
// Whitespace is collapsed and the drawing's typographic apostrophe folded to a
// plain one, since HTML collapses the first and renders the second identically.
// Nothing else about the sentence may differ.
const DRAWING = readFileSync("../docs/design/prototype.html", "utf8")
  .replaceAll("&rsquo;", "'")
  .replace(/\s+/g, " ");

describe("the settled design", () => {
  it("discloses the AI system where a test is submitted", () => {
    expect(DRAWING).toContain(AI_SYSTEM_DISCLOSURE);
  });

  it("discloses the analyst before a first message can be typed", () => {
    expect(DRAWING).toContain(ANALYST_DISCLOSURE);
  });
});
