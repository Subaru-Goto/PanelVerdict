import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import AnalystDock from "../app/components/analyst-dock";
import { ANALYST_DISCLOSURE } from "../app/lib/disclosure";
import { OPENING_REQUEST, useAnalyst } from "../app/lib/use-analyst";
import { makeResponse, manualStream } from "./fixtures";

const RESULT = makeResponse();

/** Every render goes through StrictMode, because the dev server always does
 *  (App Router turns it on by default) and its extra mount→cleanup→mount is a
 *  real hazard for a hook holding refs. A plain render once froze the whole
 *  dock in dev while this suite stayed green. */
/** The dock no longer owns its conversation — the report does, so the card and
 *  the dock share one thread. This harness stands in for that owner, without an
 *  opening message: these tests are about a reader starting the conversation. */
function DockHost() {
  return <AnalystDock analyst={useAnalyst(RESULT)} />;
}

const renderDock = () => {
  const view = render(<DockHost />, { wrapper: StrictMode });
  // The dock now starts closed: the report carries the analyst's opening
  // summary, and an open dock would only print it a second time. Every test
  // below is about the dock once a reader has reached for it.
  fireEvent.click(screen.getByRole("button", { name: /ask the analyst/i }));
  return view;
};

/** The reveal timer's period — how this test tells our interval apart from
 *  testing-library's own polling. Mirrors REVEAL_TICK_MS in use-analyst.ts. */
const REVEAL_TICK_MS = 16;

const mockFetch = (response: Response) => {
  const fetchMock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("the dock is a real dialog", () => {
  // 093 §4, and the class 057 called "the kind of thing that looks done and is
  // not": the dock was a `fixed` div with no role, no focus trap, no Escape
  // and no focus restoration. A reader on a keyboard could not reach it, and a
  // screen reader was never told a dialog had opened.

  it("announces itself as a dialog the reader can name", () => {
    renderDock();

    expect(
      screen.getByRole("dialog", { name: /ask the analyst/i }),
    ).toBeTruthy();
  });

  it("says what it is, as the dialog's own description", () => {
    // Art. 50(1) again: a screen reader must hear the disclosure when the
    // dialog opens, not only if the reader happens to browse to that line.
    renderDock();

    const dialog = screen.getByRole("dialog", { name: /ask the analyst/i });
    const describedBy = dialog.getAttribute("aria-describedby");
    expect(describedBy).toBeTruthy();
    expect(document.getElementById(describedBy!)?.textContent).toBe(
      ANALYST_DISCLOSURE,
    );
  });

  it("takes focus when it opens", () => {
    renderDock();

    const dialog = screen.getByRole("dialog", { name: /ask the analyst/i });
    expect(dialog.contains(document.activeElement)).toBe(true);
  });

  // Non-modal, decided 2026-08-27. 057 kept the dock floating because "a
  // panel that floats keeps the chart on screen while the reader asks about
  // it" — and a modal dialog takes the report away, measurably: it sets
  // `pointer-events: none` on the page and `aria-hidden` on everything behind.
  // For a screen-reader user that means the report ceases to exist while the
  // dock explains it, which is the opposite of what this work is for.
  it("leaves the report alive behind it", () => {
    render(
      <StrictMode>
        <p>the report itself</p>
        <DockHost />
      </StrictMode>,
    );
    fireEvent.click(screen.getByRole("button", { name: /ask the analyst/i }));

    expect(
      screen.getByRole("dialog", { name: /ask the analyst/i }),
    ).toBeTruthy();
    // Both of these are what a modal dialog would change, and both are what a
    // reader needs in order to look at the thing they are asking about.
    expect(document.body.style.pointerEvents).not.toBe("none");
    const report = screen.getByText("the report itself");
    expect(report.closest("[aria-hidden='true']")).toBeNull();
  });

  // Not tested here: that reaching into the report does NOT dismiss the dock.
  // jsdom cannot dispatch the trusted pointer press Radix listens for, so a
  // test for it passes whether the guard is wired or not — the un-failable
  // kind. It is verified in a browser instead, and the component says which
  // three handlers refuse it.

  it("puts focus in the dialog even while the analyst is still busy", async () => {
    // The real report opens a conversation on mount, so `busy` is true from
    // the first frame until the opening summary has finished typing out — and
    // the input is `disabled` for exactly that window. Focusing a disabled
    // input is a no-op, and having already prevented Radix's own open-focus
    // there is nothing behind it: the reader lands on `body`, hears no dialog
    // announced, and has to tab from the top of the page.
    function BusyHost() {
      return <AnalystDock analyst={useAnalyst(RESULT, OPENING_REQUEST)} />;
    }
    mockFetch(manualStream().response);
    render(<BusyHost />, { wrapper: StrictMode });
    // The opening request is sent from an effect and `busy` follows an await,
    // so let it land before reaching for the dock.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    fireEvent.click(screen.getByRole("button", { name: /ask the analyst/i }));

    const dialog = screen.getByRole("dialog", { name: /ask the analyst/i });
    expect(screen.getByLabelText(/ask about this test/i)).toHaveProperty(
      "disabled",
      true,
    );
    expect(dialog.contains(document.activeElement)).toBe(true);
  });

  it("takes the opening button out of the tab order while it is open", () => {
    // The trigger stays mounted under an opaque 384px panel anchored to the
    // same corner. Left tabbable, a keyboard reader reaches a button they
    // cannot see, and Enter shuts the dock with no visible cause.
    renderDock();

    const trigger = screen.getByRole("button", { name: /ask the analyst/i });
    expect(trigger.tabIndex).toBe(-1);
  });

  it("leaves focus alone when Escape comes from inside the report", async () => {
    // Escape is heard at the document, so it fires wherever the reader is. A
    // reader who went back to the chart and dismissed the dock from there
    // should stay where they were reading, not be thrown to the corner button.
    render(
      <StrictMode>
        <a id="in-report" href="#chart">
          back to the chart
        </a>
        <DockHost />
      </StrictMode>,
    );
    fireEvent.click(screen.getByRole("button", { name: /ask the analyst/i }));

    const inReport = document.getElementById("in-report") as HTMLElement;
    inReport.focus();
    fireEvent.keyDown(document, { key: "Escape" });

    expect(screen.queryByRole("dialog")).toBeNull();
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(document.activeElement).toBe(inReport);
  });

  it("closes on Escape and hands focus back to what opened it", async () => {
    renderDock();

    fireEvent.keyDown(document, { key: "Escape" });

    expect(screen.queryByRole("dialog")).toBeNull();
    const trigger = screen.getByRole("button", { name: /ask the analyst/i });
    // Restoration lands after the unmount, not with it, so this waits rather
    // than asserting straight away — without it a keyboard reader is left on
    // `body` and has to tab from the top of the page again.
    await waitFor(() => expect(document.activeElement).toBe(trigger));
  });
});

describe("AnalystDock", () => {
  it("discloses the AI system before a first message can be typed", () => {
    renderDock();

    // Art. 50(1): the disclosure must be in-context at latest at the first
    // interaction. The header renders it the moment the dock opens, so it is
    // on screen before the input can be used.
    expect(screen.getByText(ANALYST_DISCLOSURE)).toBeTruthy();
  });

  it("opens with the suggestion chips and streams a chip's answer", async () => {
    const stream = manualStream();
    const fetchMock = mockFetch(stream.response);
    renderDock();

    fireEvent.click(
      screen.getByRole("button", { name: "Who was on this panel?" }),
    );
    stream.push({ type: "token", text: "Five synthetic panelists " });
    stream.push({ type: "token", text: "from Japan." });
    stream.push({ type: "done" });
    stream.close();

    expect(
      await screen.findByText("Five synthetic panelists from Japan."),
    ).toBeDefined();
    // The chip's text travelled as the user message, verbatim.
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string).message).toBe(
      "Who was on this panel?",
    );
    // Chips are a seed for an empty thread, not a persistent menu.
    expect(
      screen.queryByRole("button", { name: "Who was on this panel?" }),
    ).toBeNull();
  });

  it("says it is thinking from the first instant, before any event arrives", async () => {
    // The silent seconds between send and the first stream event were real
    // dead air in live use — the draft bubble existed but showed nothing.
    const stream = manualStream();
    mockFetch(stream.response);
    renderDock();

    fireEvent.click(
      screen.getByRole("button", { name: "Who was on this panel?" }),
    );

    expect(await screen.findByText("Thinking…")).toBeDefined();

    stream.push({ type: "token", text: "Here." });
    stream.push({ type: "done" });
    stream.close();
    await screen.findByText("Here.");
    expect(screen.queryByText("Thinking…")).toBeNull();
  });

  it("shows what the analyst is doing while a tool runs, then the answer", async () => {
    const stream = manualStream();
    mockFetch(stream.response);
    renderDock();

    fireEvent.click(
      screen.getByRole("button", { name: "Why did the test stop early?" }),
    );
    stream.push({ type: "tool", name: "analyze_results" });

    expect(await screen.findByText("Checking the numbers…")).toBeDefined();

    stream.push({ type: "token", text: "It stopped because it was decisive." });
    stream.push({ type: "done" });
    stream.close();

    expect(
      await screen.findByText("It stopped because it was decisive."),
    ).toBeDefined();
    expect(screen.queryByText("Checking the numbers…")).toBeNull();
  });

  it("reveals the answer at typing speed, not as one paste", async () => {
    // gpt-5-mini writes faster than a human reads: even a genuine stream
    // lands as a paste. The pin: right after the stream closes, the full
    // sentence must NOT yet be on screen — it types its way there.
    // Short on purpose: at the placeholder reveal speed this is a few
    // hundred ms, well inside testing-library's default findBy timeout.
    const sentence = "The interval cleared the tie band by a wide margin.";
    const stream = manualStream();
    mockFetch(stream.response);
    renderDock();

    fireEvent.click(
      screen.getByRole("button", { name: "Who was on this panel?" }),
    );
    stream.push({ type: "token", text: sentence });
    stream.push({ type: "done" });
    stream.close();

    await screen.findByText(/The interval/);
    expect(screen.queryByText(sentence)).toBeNull();

    expect(await screen.findByText(sentence)).toBeDefined();
  });

  it("renders an in-band error event as the turn's outcome", async () => {
    const stream = manualStream();
    mockFetch(stream.response);
    renderDock();

    fireEvent.click(
      screen.getByRole("button", { name: "How sure are we about the winner?" }),
    );
    stream.push({
      type: "error",
      message: "analyst was still calling tools after 8 steps",
    });
    stream.close();

    expect(
      await screen.findByText(/still calling tools after 8 steps/),
    ).toBeDefined();
  });

  it("a stream that dies without done reads as a lost connection", async () => {
    const stream = manualStream();
    mockFetch(stream.response);
    renderDock();

    fireEvent.click(
      screen.getByRole("button", { name: "Who was on this panel?" }),
    );
    stream.push({ type: "token", text: "Five " });
    stream.close();

    expect(await screen.findByText(/connection was lost/i)).toBeDefined();
  });

  it("stops its reveal timer when the dock unmounts mid-stream", async () => {
    // Reachable in two clicks: ask the analyst something, then hit Evaluate
    // again — the report unmounts while the stream is still open, and a
    // surviving interval would paint a dead component until the fetch ends.
    const stream = manualStream();
    mockFetch(stream.response);
    // Identify OUR timer by its period and clear it by id: testing-library's
    // own waitFor polls on an interval too, so a bare "clearInterval was
    // called" assertion passes with no cleanup at all.
    const started = vi.spyOn(globalThis, "setInterval");
    const cleared = vi.spyOn(globalThis, "clearInterval");
    const view = renderDock();

    fireEvent.click(
      screen.getByRole("button", { name: "Who was on this panel?" }),
    );
    stream.push({ type: "token", text: "Five panelists, of whom several…" });
    await screen.findByText(/Five/);

    const revealIds = started.mock.calls
      .map((call, index) => ({
        period: call[1],
        id: started.mock.results[index]?.value,
      }))
      .filter((timer) => timer.period === REVEAL_TICK_MS)
      .map((timer) => timer.id);
    expect(revealIds).toHaveLength(1);

    view.unmount();

    expect(cleared).toHaveBeenCalledWith(revealIds[0]);
    started.mockRestore();
    cleared.mockRestore();
  });

  it("can be closed back to the launcher and reopened with the thread intact", async () => {
    const stream = manualStream();
    mockFetch(stream.response);
    renderDock();

    fireEvent.click(
      screen.getByRole("button", { name: "Who was on this panel?" }),
    );
    stream.push({ type: "token", text: "Five panelists." });
    stream.push({ type: "done" });
    stream.close();
    await screen.findByText("Five panelists.");

    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByText("Five panelists.")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Ask the analyst" }));
    expect(await screen.findByText("Five panelists.")).toBeDefined();
  });

  it("sends a typed question through the same wire", async () => {
    const stream = manualStream();
    const fetchMock = mockFetch(stream.response);
    renderDock();

    fireEvent.change(
      screen.getByRole("textbox", { name: "Ask about this test" }),
      { target: { value: "What does the tie zone mean?" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    stream.push({ type: "token", text: "It is the band of no-difference." });
    stream.push({ type: "done" });
    stream.close();

    expect(
      await screen.findByText("It is the band of no-difference."),
    ).toBeDefined();
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string).message).toBe(
      "What does the tie zone mean?",
    );
  });
});
