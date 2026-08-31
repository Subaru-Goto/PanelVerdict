import { describe, expect, it } from "vitest";

import { isPracticalTie, leadingSide, railSummary } from "../app/lib/verdict";
import { makeResponse, makeTiedResponse } from "./fixtures";

const verdict = (
  over: Partial<ReturnType<typeof makeResponse>["verdict"]>,
) => ({
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

describe("railSummary", () => {
  it("names the tie rather than a winner when the tie is itself credible", () => {
    // The case a naive A/B tool cannot express, and the reason the rail needs a
    // phrase rather than a percentage.
    expect(
      railSummary(
        verdict({ probability_practical_tie: 0.96, credible_mass: 0.95 }),
      ),
    ).toBe("too close to call");
  });

  it("states the leading side's own share, not B's", () => {
    // 0.288 prefer B, so 71% prefer the first — the figure the rail shows has
    // to be the winner's, or a clear win for A reads as a 29% one.
    expect(
      railSummary(
        verdict({
          share_preferring_b: 0.288,
          probability_practical_tie: 0.016,
          credible_mass: 0.95,
        }),
      ),
    ).toBe("71% preferred the first");
  });

  it("says second when B leads", () => {
    expect(
      railSummary(
        verdict({
          share_preferring_b: 0.66,
          probability_practical_tie: 0.02,
          credible_mass: 0.95,
        }),
      ),
    ).toBe("66% preferred the second");
  });

  it("agrees with the report about whether the panel called it", () => {
    // One threshold, not two: the rail's phrase and the report's lead must
    // switch together, which is why the phrase is derived from isPracticalTie
    // rather than from a share cutoff of its own.
    const tie = verdict({
      probability_practical_tie: 0.96,
      credible_mass: 0.95,
    });

    expect(isPracticalTie(tie)).toBe(true);
    expect(railSummary(tie)).toBe("too close to call");
  });
});
