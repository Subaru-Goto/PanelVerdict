import { describe, expect, it } from "vitest";

import { isPracticalTie, leadingSide } from "../app/lib/verdict";
import { makeResponse, makeTiedResponse } from "./fixtures";

const verdict = (over: Partial<ReturnType<typeof makeResponse>["verdict"]>) => ({
  ...makeResponse().verdict,
  ...over,
});

describe("leadingSide", () => {
  it("reads B's share, not B's name", () => {
    expect(leadingSide(verdict({ share_preferring_b: 0.7 }))).toBe("b");
    expect(leadingSide(verdict({ share_preferring_b: 0.3 }))).toBe("a");
  });

  it("gives an exactly even panel to B", () => {
    // Arbitrary but load-bearing: the chart places the annotation on the half
    // this does *not* pick, so both have to split at the same value and in the
    // same direction. 100 of 200 puts the mean at exactly 0.5.
    expect(leadingSide(verdict({ share_preferring_b: 0.5 }))).toBe("b");
  });
});

describe("isPracticalTie", () => {
  it("is true once the tie's own probability clears the credible mass", () => {
    // The boundary is inclusive, and a real tie sits right on it: a run stops
    // the moment the probability crosses, so the reported figure is barely
    // over. An exclusive `>` would silently drop the panels this exists for.
    expect(isPracticalTie(makeTiedResponse().verdict)).toBe(true);
    expect(
      isPracticalTie(
        verdict({ probability_practical_tie: 0.95, credible_mass: 0.95 }),
      ),
    ).toBe(true);
    expect(
      isPracticalTie(
        verdict({ probability_practical_tie: 0.9499, credible_mass: 0.95 }),
      ),
    ).toBe(false);
  });

  it("is false for the panel the rest of the suite runs on", () => {
    expect(isPracticalTie(makeResponse().verdict)).toBe(false);
  });
});
