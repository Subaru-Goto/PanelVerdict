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

    expect(
      screen.getByText(/^Mean — the estimated split: 29% prefer B\.$/),
    ).toBeTruthy();
    expect(
      screen.getByText(/B’s true share sits between 17% and 42% \(95% sure\)/),
    ).toBeTruthy();
    expect(
      screen.getByText(/tie zone: splits from 43% to 57% read as even/),
    ).toBeTruthy();
  });

  it("annotates the mean line on the chart in both directions", () => {
    // The chart lives in B-space, so the leading side's share appeared nowhere
    // on the plot — the reader had to compute 100 − 29 at the dashed line.
    render(<Report result={makeResponse()} />);

    expect(
      screen.getByText(/^estimated split: 71% prefer A · 29% prefer B/),
    ).toBeTruthy();
  });

  it("writes each edge's number at its mark on the chart", () => {
    // The axis has no ticks, so a number that lives only in the legend names a
    // position the eye cannot find on the plot.
    render(<Report result={makeResponse()} />);

    const svg = screen.getByRole("img", { name: /posterior distribution/i });
    for (const edge of ["17%", "42%", "43%", "57%"]) {
      expect(svg.textContent).toContain(edge);
    }
  });

  it("anchors the axis ends with the direction and the actual headline text", () => {
    render(<Report result={makeResponse()} />);

    const left = screen.getByText(/^← prefer A/);
    const right = screen.getByText(/^prefer B/);
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

describe("vote feed", () => {
  it("shows the voter as a person, never their database handle", () => {
    // 023: a persona id identifies a row, not a reader. The demographic line is
    // what makes the reason beside it evidence.
    render(<Report result={makeResponse()} />);

    expect(screen.queryByText(/US-00042/)).toBeNull();
    expect(
      screen.getByText(/34 · female · US · university degree · upper income/),
    ).toBeTruthy();
  });

  it("keeps the Big Five behind a disclosure, in the chip vocabulary", () => {
    render(<Report result={makeResponse()} />);

    expect(screen.getByText("personality")).toBeTruthy();
    expect(screen.getByText(/agreeableness: very low/)).toBeTruthy();
    expect(screen.getByText(/conscientiousness: very high/)).toBeTruthy();
  });

  it("says the voters are synthetic", () => {
    // The demographics look real enough to ask — so the copy answers before
    // anyone has to.
    render(<Report result={makeResponse()} />);

    expect(
      screen.getByText(/synthetic panelists — sampled personas, not real people/),
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
