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
import { posteriorDensity } from "../app/lib/beta";

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

describe("the lead", () => {
  it("names both headlines, the winner first", () => {
    renderReport();

    // The chart's axis names both headlines too, so the loser is matched by
    // the lead's own phrasing rather than by its text alone.
    expect(screen.getByText(/^“Save 50% today”$/)).toBeTruthy();
    expect(screen.getByText(/over “Members save half”/)).toBeTruthy();
  });

  it("says the probability in words, and it is the meaningfully-preferred one", () => {
    // 98% is probability_meaningfully_preferred.a — the mass past the tie zone,
    // which is what the chart shades. Reading share_preferring_b's complement
    // here instead would print 71%: a different question, and the swap this
    // test exists to catch.
    renderReport();

    expect(
      screen.getByText("98% likely people genuinely prefer this one."),
    ).toBeTruthy();
  });

  it("says what the percentage already excludes, after the claim", () => {
    // 020 keeps the band load-bearing. It explains what the number counts
    // rather than adding a claim, so it follows the sentence it qualifies.
    renderReport();

    expect(
      screen.getByText(
        /Wins too small to matter don’t count towards that number/,
      ),
    ).toBeTruthy();
  });

  it("counts the panelists who preferred it, which nothing else states", () => {
    renderReport();

    expect(screen.getByText(/36 of 50 panelists preferred it/)).toBeTruthy();
  });

  it("crowns no winner with a label", () => {
    // 020 deleted this label from the payload; re-deriving it in the UI puts
    // it back. Not at any size, so a redesign cannot reintroduce it as a
    // heading.
    renderReport();

    expect(screen.queryByText(/Panel leans clearly/)).toBeNull();
    expect(screen.queryByText(/No call at this credibility/)).toBeNull();
  });
});

describe("stat tiles", () => {
  it("are gone, because each number they held is stated somewhere else", () => {
    renderReport();

    for (const label of [
      "Share preferring B",
      "Chance A is preferred",
      "Chance B is preferred",
      "Practical tie",
    ]) {
      expect(screen.queryByText(label)).toBeNull();
    }
  });

  it("does not print the lead's percentage a second time in prose", () => {
    // "Every number appears exactly once on the page" — the tiles printed the
    // same posterior partitioned three ways.
    //
    // The chart is the one deliberate exception, and it is not a restatement:
    // it draws the figure as the area it measures, which is what makes the mean
    // and the probability distinguishable at all. So the count is taken over
    // the prose, and a tile coming back still fails here.
    const { container } = renderReport();
    container.querySelector("figure")?.remove();

    // Per element, not over one flattened string: a tile renders its label and
    // its value as siblings, and flattening glues them into "...preferred98%",
    // where \b has no boundary left to match. The guard would then pass on
    // exactly the regression it exists to catch.
    const printed = Array.from(container.querySelectorAll("*")).filter(
      (node) =>
        node.children.length === 0 && /\b98%/.test(node.textContent ?? ""),
    );
    expect(printed).toHaveLength(1);
  });
});

describe("what the panel could and could not resolve", () => {
  it("keeps the gap this panel could detect, which no other line carries", () => {
    renderReport();

    expect(
      screen.getByText(/can only detect leans of 16.7 points or more/),
    ).toBeTruthy();
  });
});

describe("the lead and the curve agree", () => {
  it("prints a percentage the chart's own curve arrives at independently", () => {
    // The prototype recorded getting this wrong once: a ROPE fixture "made
    // that mass ~98%, silently contradicting the headline". The lead prints
    // the payload's probability; the curve is rebuilt from the raw votes. Two
    // routes to one quantity, so they have to land in the same place — and a
    // fixture edit that breaks the arithmetic fails here rather than shipping
    // a report that disagrees with its own chart.
    const { verdict, tally } = makeResponse();

    const curve = posteriorDensity(
      tally.counts.a ?? 0,
      tally.counts.b ?? 0,
      2001,
    );
    const mass = (keep: (p: number) => boolean): number =>
      curve
        .filter((point) => keep(point.p))
        .reduce((sum, x) => sum + x.density, 0);
    // The curve runs over B's share, so A is meaningfully preferred where that
    // share sits below the band.
    const pastBand = mass((p) => p < verdict.rope[0]) / mass(() => true);

    expect(pastBand).toBeCloseTo(
      verdict.probability_meaningfully_preferred.a,
      2,
    );
  });
});

describe("a practical tie", () => {
  // 020 keeps `practical_tie` as a flag, not a bucket: a positive finding
  // added to the probability rather than replacing it.
  const tied = () => {
    const result = makeResponse();
    return {
      ...result,
      verdict: {
        ...result.verdict,
        probability_meaningfully_preferred: { a: 0.02, b: 0.02 },
        probability_practical_tie: 0.96,
      },
    };
  };

  it("says the two are equally good, without dropping the probability", () => {
    renderReport(tied());

    expect(screen.getByText(/these two are equally good/i)).toBeTruthy();
    expect(
      screen.getByText("2% likely people genuinely prefer this one."),
    ).toBeTruthy();
  });

  it("stays quiet when the tie is not credible", () => {
    renderReport();

    expect(screen.queryByText(/these two are equally good/i)).toBeNull();
  });
});

describe("posterior chart", () => {
  const LEGEND = { name: /what each mark on the chart means/i };

  // The prototype principle, learned over three consecutive "what is this
  // line?" questions: every visible mark carries an on-screen name, or it is
  // deleted. The number belongs on the plot, at the mark it measures; the
  // legend says what the mark *means*, in plain words before the jargon.
  it("reads as a glossary: plain words first, the technical name after", () => {
    renderReport();

    const legend = screen.getByRole("list", LEGEND);
    for (const [plain, technical] of [
      ["Genuinely preferred", "(posterior probability)"],
      ["Most likely", "(mean)"],
      ["Plausible range", "(95% HDI)"],
      ["Practically a tie", "(ROPE)"],
    ]) {
      expect(legend.textContent).toContain(plain);
      expect(legend.textContent).toContain(technical);
    }
  });

  it("states no figure the plot already draws", () => {
    // This slice's whole point. The legend used to restate the mean, both HDI
    // ends, both ROPE ends, and the credible mass a second time inside its own
    // sentence — every one of them drawn at its own mark a few pixels away.
    renderReport();

    const legend = screen.getByRole("list", LEGEND);
    for (const drawn of ["29%", "17%", "42%", "43%", "57%"]) {
      expect(legend.textContent).not.toContain(drawn);
    }
  });

  it("tells a screen reader what the marks it cannot see say", () => {
    // The plot is one `img`, so nothing inside it is announced. Everything the
    // eye gets from the marks has to be in the label or it is not there at all.
    renderReport();

    const svg = screen.getByRole("img", { name: /posterior distribution/i });
    const label = svg.getAttribute("aria-label") ?? "";
    // Everything the eye gets from a mark has to be in this string, because
    // `role="img"` means nothing inside the plot is announced at all.
    expect(label).toContain("71% preferring A and 29% preferring B");
    expect(label).toContain("between 17% and 42% at 95% credibility");
    expect(label).toContain("98% of the curve lies past the tie zone");
    expect(label).toContain("on A's side.");
  });

  it("lands its leader line inside the area it points at", () => {
    // A near-tie shades a thin sliver just past the band, and aiming at the
    // middle of that sliver's *width* aims at where the curve has already gone
    // flat — the line then points at blank paper. Checked geometrically
    // against the shape actually rendered, not against the rule that made it.
    const near = makeResponse();
    const { container } = renderReport({
      ...near,
      verdict: {
        ...near.verdict,
        share_preferring_b: 0.52,
        credible_interval: [0.41, 0.63],
        probability_meaningfully_preferred: { a: 0.14, b: 0.22 },
        probability_practical_tie: 0.64,
      },
      tally: { counts: { a: 24, b: 26 }, total: 50 },
    });

    const shape = (
      (
        container.querySelector('[data-mark="mass"]')?.getAttribute("d") ?? ""
      ).match(/-?[\d.]+,-?[\d.]+/g) ?? []
    ).map((pair) => {
      const [px, py] = pair.split(",").map(Number);
      return { x: px, y: py };
    });
    const leader = container.querySelector('[data-mark="leader"]');
    const tipX = Number(leader?.getAttribute("x2"));
    const tipY = Number(leader?.getAttribute("y2"));

    // SVG y grows downward: the axis is the largest y, the area's tallest
    // point the smallest.
    const baseline = Math.max(...shape.map((point) => point.y));
    const tallest = Math.min(...shape.map((point) => point.y));

    // The rule, stated as something the shape can disagree with: the tip must
    // sit at the region's *tallest* column. Comparing the tip's height to the
    // region's would only restate how the tip is computed — half of a height
    // is always half of that height, whichever column it was taken from.
    // The polygon's two closing anchors sit on the axis at the same x as the
    // band edge, so the curve's own points are the ones to compare against.
    const curve = shape.filter((point) => point.y < baseline);
    const atTip = curve.reduce((best, point) =>
      Math.abs(point.x - tipX) < Math.abs(best.x - tipX) ? point : best,
    );
    expect(atTip.y).toBeCloseTo(tallest, 1);

    // And that column has to be worth pointing at. A fixture whose shaded
    // region is a hairline would satisfy the rule above and still leave the
    // line ending on blank paper, so the fixture's own geometry is pinned.
    expect(baseline - tallest).toBeGreaterThan(20);
    expect(baseline - tipY).toBeGreaterThan(10);
  });

  it("keeps a decisive panel's interval bounds inside the plot", () => {
    // A decisive verdict pushes the interval against the plot's edge, and a
    // label anchored outside a bar that has no outside left was drawn past the
    // viewBox: the lower bound rendered as a bare "%" with its digits cut off.
    const decisive = makeResponse();
    const { container } = renderReport({
      ...decisive,
      verdict: {
        ...decisive.verdict,
        share_preferring_b: 0.06,
        credible_interval: [0.02, 0.14],
        probability_meaningfully_preferred: { a: 0.999, b: 0.0 },
      },
      tally: { counts: { a: 47, b: 3 }, total: 50 },
    });

    const svg = screen.getByRole("img", { name: /posterior distribution/i });
    const width = Number(svg.getAttribute("viewBox")?.split(" ")[2]);
    for (const mark of ["cri-low", "cri-high"]) {
      const label = container.querySelector(`[data-mark="${mark}"]`);
      const at = Number(label?.getAttribute("x"));
      // Anchored text runs away from its x, so the room it needs is on the
      // side it grows towards.
      const room =
        label?.getAttribute("text-anchor") === "end" ? at : width - at;
      expect(label?.textContent).toMatch(/^\d+%$/);
      expect(room).toBeGreaterThan(20);
    }
  });

  it("writes the probability onto the area that is the probability", () => {
    // The author read the prototype and took the mean for the answer. Both are
    // on this chart, and only one of them is the answer — so the answer is
    // written on the region it measures, with a leader line into it.
    renderReport();

    const svg = screen.getByRole("img", { name: /posterior distribution/i });
    expect(svg.textContent).toContain("98%");
    expect(svg.textContent?.toLowerCase()).toContain("posterior probability");
  });

  it("shades the leader's tail, whichever side leads", () => {
    // The mass past the band is the lead's number. In the fixture A leads, so
    // it lies below the band; a B-leading verdict must move it above, or the
    // chart would draw the loser's tail and label it with the winner's figure.
    const shadedRange = (container: HTMLElement) => {
      const shade = container.querySelector('[data-mark="mass"]');
      const xs = (shade?.getAttribute("d") ?? "")
        .split(/[ML]/)
        .filter(Boolean)
        .map((point) => Number(point.split(",")[0]));
      return { low: Math.min(...xs), high: Math.max(...xs) };
    };

    const bandEdges = (container: HTMLElement) => {
      const band = container.querySelector('[data-mark="rope"]');
      const left = Number(band?.getAttribute("x"));
      return { left, right: left + Number(band?.getAttribute("width")) };
    };

    const aLeads = renderReport().container;
    expect(shadedRange(aLeads).high).toBeCloseTo(bandEdges(aLeads).left, 1);
    cleanup();
    // A second mount opens a second conversation, and `beforeEach` handed out
    // one Response whose body a stream can only be read from once. Without a
    // fresh one the re-render races a drained reader.
    stream = manualStream();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(stream.response));

    const flipped = makeResponse();
    const bLeads = renderReport({
      ...flipped,
      verdict: {
        ...flipped.verdict,
        share_preferring_b: 0.712,
        credible_interval: [0.582, 0.827],
        probability_meaningfully_preferred: { a: 0.0, b: 0.984 },
      },
      tally: { counts: { a: 14, b: 36 }, total: 50 },
    }).container;
    expect(shadedRange(bLeads).low).toBeCloseTo(bandEdges(bLeads).right, 1);
  });

  it("writes each edge's number at its mark on the chart", () => {
    // The axis has no ticks, so a number that lives only in the legend names a
    // position the eye cannot find on the plot.
    renderReport();

    const svg = screen.getByRole("img", { name: /posterior distribution/i });
    for (const edge of ["17%", "42%"]) {
      expect(svg.textContent).toContain(edge);
    }
  });

  it("annotates the mean line on the chart in both directions", () => {
    // The chart lives in B-space, so the leading side's share appeared nowhere
    // on the plot — the reader had to compute 100 - 29 at the dashed line.
    renderReport();

    expect(
      screen.getByText(/^estimated split: 71% prefer A \u00b7 29% prefer B$/),
    ).toBeTruthy();
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
      screen.getByText(
        /how likely each possible split .* given these 50 votes/i,
      ),
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
      screen.getByText(
        /synthetic panelists — sampled personas, not real people/,
      ),
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
    expect(
      (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls,
    ).toHaveLength(1);
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

    const dock = screen.getByRole("dialog", { name: /ask the analyst/i });
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

  it("shows a reader's own question even before its answer arrives", async () => {
    // The opening exchange is dropped by finding the reader's first message,
    // not by slicing a fixed two turns. `send` happens to append a user and an
    // analyst turn together, so two was right — but that is an invariant of
    // `send` enforced nowhere, and a slice would eat a real message the day it
    // changed. This is the case that would have caught it.
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

    const dock = screen.getByRole("dialog", { name: /ask the analyst/i });
    await waitFor(() =>
      expect(dock.textContent).toContain("Which of them said that?"),
    );
    // And still no trace of the report's own opening exchange.
    expect(dock.textContent).not.toContain("They liked belonging.");
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
