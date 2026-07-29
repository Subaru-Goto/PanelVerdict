import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import AnalystDock from "../app/components/analyst-dock";
import { makeResponse } from "./fixtures";

const RESULT = makeResponse();

/** A /chat response whose NDJSON lines are fed one enqueue at a time, so a
 *  test can assert what the dock shows BETWEEN events — the transient tool
 *  status is only visible mid-stream. */
const manualStream = () => {
  const encoder = new TextEncoder();
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c;
    },
  });
  return {
    response: new Response(body, { status: 200 }),
    push: (event: object) =>
      controller.enqueue(encoder.encode(JSON.stringify(event) + "\n")),
    close: () => controller.close(),
  };
};

const mockFetch = (response: Response) => {
  const fetchMock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("AnalystDock", () => {
  it("opens with the suggestion chips and streams a chip's answer", async () => {
    const stream = manualStream();
    const fetchMock = mockFetch(stream.response);
    render(<AnalystDock result={RESULT} />);

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

  it("shows what the analyst is doing while a tool runs, then the answer", async () => {
    const stream = manualStream();
    mockFetch(stream.response);
    render(<AnalystDock result={RESULT} />);

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

  it("renders an in-band error event as the turn's outcome", async () => {
    const stream = manualStream();
    mockFetch(stream.response);
    render(<AnalystDock result={RESULT} />);

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
    render(<AnalystDock result={RESULT} />);

    fireEvent.click(
      screen.getByRole("button", { name: "Who was on this panel?" }),
    );
    stream.push({ type: "token", text: "Five " });
    stream.close();

    expect(await screen.findByText(/connection was lost/i)).toBeDefined();
  });

  it("can be closed back to the launcher and reopened with the thread intact", async () => {
    const stream = manualStream();
    mockFetch(stream.response);
    render(<AnalystDock result={RESULT} />);

    fireEvent.click(
      screen.getByRole("button", { name: "Who was on this panel?" }),
    );
    stream.push({ type: "token", text: "Five panelists." });
    stream.push({ type: "done" });
    stream.close();
    await screen.findByText("Five panelists.");

    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByText("Five panelists.")).toBeNull();

    fireEvent.click(
      screen.getByRole("button", { name: "Ask the analyst" }),
    );
    expect(await screen.findByText("Five panelists.")).toBeDefined();
  });

  it("sends a typed question through the same wire", async () => {
    const stream = manualStream();
    const fetchMock = mockFetch(stream.response);
    render(<AnalystDock result={RESULT} />);

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
