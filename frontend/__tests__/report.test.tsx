import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import Report from "../app/components/report";
import { makeResponse, manualStream } from "./fixtures";
import { OPENING_REQUEST } from "../app/lib/use-analyst";

/** The report opens a conversation on mount, so every render here would reach
 *  the network. Each test gets a stream it can drive, and StrictMode because
 *  the dev server always mounts twice. */
let stream: ReturnType<typeof manualStream>;

beforeEach(() => {
  stream = manualStream();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(stream.response));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const renderReport = (result = makeResponse()) =>
  render(<Report result={result} />, { wrapper: StrictMode });

describe("verdict line", () => {
  it("names the leading headline with its share of the panel", () => {
    renderReport();

    expect(screen.getByText("Save 50% today")).toBeTruthy();
    expect(screen.getByText(/71% of the panel prefer it/)).toBeTruthy();
  });
});

describe("stat tiles", () => {
  it("states both preference probabilities and the tie", () => {
    // The 98% is probability_meaningfully_preferred.a, read straight onto A's
    // tile — a swap here is the bug this test exists to catch.
    renderReport();

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
    renderReport();

    expect(
      screen.getByText(/true share is between 17% and 42% \(95% sure\)/),
    ).toBeTruthy();
  });
});

describe("posterior chart", () => {
  // The prototype principle, learned over three consecutive "what is this
  // line?" questions: every visible mark carries an on-screen name and number,
  // or it is deleted.
  it("names every mark in the legend with its number", () => {
    renderReport();

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
    renderReport();

    expect(
      screen.getByText(/^estimated split: 71% prefer A · 29% prefer B/),
    ).toBeTruthy();
  });

  it("writes each edge's number at its mark on the chart", () => {
    // The axis has no ticks, so a number that lives only in the legend names a
    // position the eye cannot find on the plot.
    renderReport();

    const svg = screen.getByRole("img", { name: /posterior distribution/i });
    for (const edge of ["17%", "42%", "43%", "57%"]) {
      expect(svg.textContent).toContain(edge);
    }
  });

  it("anchors the axis ends with the direction and the actual headline text", () => {
    renderReport();

    const left = screen.getByText(/^← prefer A/);
    const right = screen.getByText(/^prefer B/);
    expect(left.textContent).toContain("Save 50% today");
    expect(right.textContent).toContain("Members save half");
  });

  it("says what the curve is, tied to this run's vote count", () => {
    renderReport();

    expect(
      screen.getByText(/how likely each possible split .* given these 50 votes/i),
    ).toBeTruthy();
  });
});

describe("vote feed", () => {
  it("shows the voter as a person, never their database handle", () => {
    // A persona id identifies a row, not a reader. The demographic line is
    // what makes the reason beside it evidence.
    renderReport();

    expect(screen.queryByText(/US-00042/)).toBeNull();
    expect(
      screen.getByText(/34 · female · US · university degree · upper income/),
    ).toBeTruthy();
  });

  it("keeps the Big Five behind a disclosure, in the chip vocabulary", () => {
    renderReport();

    expect(screen.getByText("personality")).toBeTruthy();
    expect(screen.getByText(/agreeableness: very low/)).toBeTruthy();
    expect(screen.getByText(/conscientiousness: very high/)).toBeTruthy();
  });

  it("says the voters are synthetic", () => {
    // The demographics look real enough to ask — so the copy answers before
    // anyone has to.
    renderReport();

    expect(
      screen.getByText(/synthetic panelists — sampled personas, not real people/),
    ).toBeTruthy();
  });
});

describe("panel card", () => {
  it("shows each trait as a chip carrying its source phrase", () => {
    // The source phrase is the only part of the trait
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

describe("the opening summary", () => {
  it("opens the conversation exactly once, even mounted twice", async () => {
    // StrictMode runs the effect twice and dev always runs StrictMode, so a
    // naive mount-effect would buy two model calls per report.
    renderReport();
    stream.push({ type: "token", text: "Most who picked A wanted a number." });
    stream.push({ type: "done" });
    stream.close();

    expect(
      await screen.findByText("Most who picked A wanted a number."),
    ).toBeTruthy();
    expect((globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls).toHaveLength(1);
  });

  it("puts the summary above the panelists, who start collapsed", async () => {
    const { container } = renderReport();
    stream.push({ type: "token", text: "They liked belonging." });
    stream.push({ type: "done" });
    stream.close();

    const summary = await screen.findByText("They liked belonging.");
    const panelists = screen.getByText(/what the panelists said/i);
    expect(
      summary.compareDocumentPosition(panelists) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    // Detail is a click away, not a scroll past.
    expect(container.querySelector("details[open]")).toBeNull();
  });

  it("does not print the summary a second time when the dock opens", async () => {
    // The opening exchange belongs to the report, and the card above already
    // shows it. Reprinting it a hand's breadth below is duplication rather than
    // context — neither the question, which the reader never typed, nor the
    // answer, which is already on the page.
    renderReport();
    stream.push({ type: "token", text: "They liked belonging." });
    stream.push({ type: "done" });
    stream.close();
    await screen.findByText("They liked belonging.");

    fireEvent.click(screen.getByRole("button", { name: /ask the analyst/i }));

    const dock = screen.getByRole("region", { name: /analyst chat/i });
    expect(dock.textContent).not.toContain("They liked belonging.");
    expect(dock.textContent).not.toContain(OPENING_REQUEST);
    // Hidden from the transcript, not re-fetched: still one call.
    expect(
      (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls,
    ).toHaveLength(1);
  });

  it("still continues the report's own thread when the reader asks", async () => {
    // Hidden is not discarded. The summary stays in the analyst's context, so
    // a follow-up resolves against it instead of re-buying the tool calls —
    // which is the whole reason the card and the dock share one thread.
    renderReport();
    stream.push({ type: "token", text: "They liked belonging." });
    stream.push({ type: "done" });
    stream.close();
    await screen.findByText("They liked belonging.");

    fireEvent.click(screen.getByRole("button", { name: /ask the analyst/i }));
    fireEvent.change(screen.getByLabelText(/ask about this test/i), {
      target: { value: "Which of them said that?" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^send$/i }));

    const fetchMock = globalThis.fetch as ReturnType<typeof vi.fn>;
    await waitFor(() => expect(fetchMock.mock.calls).toHaveLength(2));
    const threads = fetchMock.mock.calls.map(
      ([, init]) => JSON.parse((init as RequestInit).body as string).thread_id,
    );
    expect(threads[1]).toBe(threads[0]);
  });

  it("keeps the synthetic caveat out of the collapsed half", async () => {
    // A summary reads like a finding, which is exactly when a reader forgets
    // the panel is synthetic — so the caveat cannot hide with the list.
    renderReport();
    stream.push({ type: "token", text: "A won on concreteness." });
    stream.push({ type: "done" });
    stream.close();

    await screen.findByText("A won on concreteness.");
    const caveat = screen.getByText(/synthetic/i);
    expect(caveat.closest("details")).toBeNull();
  });
});
