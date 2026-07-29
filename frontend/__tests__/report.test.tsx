import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import Report from "../app/components/report";
import { makeResponse } from "./fixtures";

afterEach(cleanup);

describe("verdict line", () => {
  it("names the leading headline with its share of the panel", () => {
    render(<Report result={makeResponse()} />);

    expect(screen.getByText("Save 50% today")).toBeTruthy();
    expect(screen.getByText(/71% of the panel prefer it/)).toBeTruthy();
  });
});

describe("stat tiles", () => {
  it("states both preference probabilities and the tie", () => {
    // The 98% is probability_meaningfully_preferred.a, read straight onto A's
    // tile — a swap here is the bug this test exists to catch.
    render(<Report result={makeResponse()} />);

    const tileA = screen.getByText("Chance A is preferred");
    expect(tileA.parentElement?.textContent).toContain("98%");
    const tileB = screen.getByText("Chance B is preferred");
    expect(tileB.parentElement?.textContent).toContain("0%");
    expect(screen.getByText("Practical tie")).toBeTruthy();
    expect(
      screen.getByText(/chance the true split lands in the tie zone/),
    ).toBeTruthy();
    expect(
      screen.getByText(/can only detect leans of 16.7 points or more/),
    ).toBeTruthy();
  });

  it("keeps the credible interval beside the share, in plain words", () => {
    render(<Report result={makeResponse()} />);

    expect(
      screen.getByText(/true share is between 17% and 42% \(95% sure\)/),
    ).toBeTruthy();
  });
});

describe("posterior chart", () => {
  // The 011 prototype principle, learned over three consecutive "what is this
  // line?" questions: every visible mark carries an on-screen name and number,
  // or it is deleted.
  it("names every mark in the legend with its number", () => {
    render(<Report result={makeResponse()} />);

    expect(screen.getByText(/Mean — the panel’s best guess: 29% prefer B/))
      .toBeTruthy();
    expect(
      screen.getByText(/true share sits between 17% and 42% \(95% sure\)/),
    ).toBeTruthy();
    expect(
      screen.getByText(/tie zone: splits from 43% to 57% read as even/),
    ).toBeTruthy();
  });

  it("anchors the axis ends with the scale and the actual headline text", () => {
    render(<Report result={makeResponse()} />);

    const left = screen.getByText(/^← 0% prefer B/);
    const right = screen.getByText(/100% prefer B/);
    expect(left.textContent).toContain("Save 50% today");
    expect(right.textContent).toContain("Members save half");
  });

  it("says what the curve is, tied to this run's vote count", () => {
    render(<Report result={makeResponse()} />);

    expect(
      screen.getByText(/how likely each possible split .* given these 50 votes/i),
    ).toBeTruthy();
  });
});

describe("panel card", () => {
  it("shows each trait as a chip carrying its source phrase", () => {
    // The 017 amendment: the source phrase is the only part of the trait
    // reading a customer can check, so the chip must carry it.
    const base = makeResponse();
    render(
      <Report
        result={{
          ...base,
          query: {
            ...base.query,
            traits: [
              {
                trait: "conscientiousness",
                level: "high",
                source_phrase: "cautious",
              },
            ],
          },
        }}
      />,
    );

    const chip = screen.getByText(/conscientiousness: high/);
    expect(chip.textContent).toContain("cautious");
  });

  it("wears a coverage badge only when the panel is not what was asked for", () => {
    const base = makeResponse();
    const { rerender } = render(<Report result={base} />);
    expect(screen.queryByText(/coverage:/)).toBeNull();

    rerender(
      <Report
        result={{
          ...base,
          query: { ...base.query, coverage: "unmatched" as const },
        }}
      />,
    );
    expect(screen.getByText(/coverage: unmatched/)).toBeTruthy();
  });
});
