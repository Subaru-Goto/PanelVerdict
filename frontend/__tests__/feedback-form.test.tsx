import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import Report from "../app/components/report";
import { FeedbackBoundary } from "../app/components/report-boundary";
import { makeResponse, manualStream } from "./fixtures";

// The live report also opens an analyst turn on mount; the mock answers by
// path so the feedback POST can be asserted on its own.
const fetchByPath = (feedback: () => Response) => {
  const fetchMock = vi.fn<
    (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>
  >((input) => {
    const url = typeof input === "string" ? input : input.toString();
    return Promise.resolve(
      url.endsWith("/api/feedback") ? feedback() : manualStream().response,
    );
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
};

const PROMPT = /Something unclear or wrong here\? Tell us\./;

beforeEach(() => {
  fetchByPath(() => new Response(null, { status: 204 }));
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("the feedback form at the foot of a report (053/#150)", () => {
  it("is on a live report and not on the locked sample", () => {
    render(
      <Report result={makeResponse()} testId="t-1" onRefresh={() => {}} />,
    );
    expect(screen.getByText(PROMPT)).toBeTruthy();
    cleanup();

    render(<Report result={makeResponse()} analyst="locked" />);
    expect(screen.queryByText(PROMPT)).toBeNull();
  });

  it("sends the text against this test and says it is read, not replied to", async () => {
    const fetchMock = fetchByPath(() => new Response(null, { status: 204 }));
    render(
      <Report result={makeResponse()} testId="t-1" onRefresh={() => {}} />,
    );

    fireEvent.change(screen.getByLabelText(PROMPT), {
      target: { value: "I could not tell what to ship." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send feedback" }));

    await waitFor(() =>
      expect(
        screen.getByText("Thanks. Feedback is read, not replied to."),
      ).toBeTruthy(),
    );
    const call = fetchMock.mock.calls.find(([input]) =>
      String(input).endsWith("/api/feedback"),
    );
    expect(call).toBeDefined();
    const init = call?.[1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({
      test_id: "t-1",
      body: "I could not tell what to ship.",
    });
    expect(screen.queryByLabelText(PROMPT)).toBeNull();
  });

  it("keeps what was typed when the send fails, and says so", async () => {
    fetchByPath(() => new Response(null, { status: 500 }));
    render(
      <Report result={makeResponse()} testId="t-1" onRefresh={() => {}} />,
    );

    fireEvent.change(screen.getByLabelText(PROMPT), {
      target: { value: "the chart is unreadable" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send feedback" }));

    await waitFor(() =>
      expect(
        screen.getByText(
          "Could not send. Your message is still here, try again.",
        ),
      ).toBeTruthy(),
    );
    expect((screen.getByLabelText(PROMPT) as HTMLTextAreaElement).value).toBe(
      "the chart is unreadable",
    );
    expect(
      (
        screen.getByRole("button", {
          name: "Send feedback",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false);
  });

  it("cannot send an empty message", () => {
    render(
      <Report result={makeResponse()} testId="t-1" onRefresh={() => {}} />,
    );
    expect(
      (
        screen.getByRole("button", {
          name: "Send feedback",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
  });
});

describe("the feedback boundary", () => {
  it("says one sentence and keeps the rest of the page", () => {
    const Broken = () => {
      throw new Error("form bug");
    };
    const quiet = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <div>
        <p>The verdict</p>
        <FeedbackBoundary>
          <Broken />
        </FeedbackBoundary>
      </div>,
    );
    quiet.mockRestore();

    expect(screen.getByText("The verdict")).toBeTruthy();
    expect(
      screen.getByText(
        "The feedback box is unavailable right now. The report is unaffected.",
      ),
    ).toBeTruthy();
  });
});
