import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { makeResponse } from "./fixtures";

const evaluateMock = vi.fn();
const myTestMock = vi.fn();
const streamChatMock = vi.fn();

const OTHER = {
  ...makeResponse(),
  variants: { a: "Older line", b: "Its rival" },
};

vi.mock("../app/lib/api", () => ({
  evaluate: (input: unknown) => evaluateMock(input),
  resumeEvaluate: () => Promise.reject(new Error("not used")),
  LOCALES: ["US", "JP", "DE"],
  MIN_PANEL_AGE: 18,
  MAX_PANEL_AGE: 100,
  myTests: () =>
    Promise.resolve({
      tests: [
        {
          test_id: "t-older",
          created_at: "2026-08-30T10:00:00Z",
          variants: OTHER.variants,
          verdict: OTHER.verdict,
          tally: OTHER.tally,
        },
      ],
      next_cursor: null,
    }),
  myTest: (id: string) => myTestMock(id),
  forgetTest: () => Promise.resolve(),
  onRunsChanged: () => () => {},
}));

vi.mock("../app/lib/auth", () => ({
  onAuthChange: (listener: (value: boolean) => void) => {
    listener(true);
    return () => {};
  },
  authHeaders: () => Promise.resolve({}),
  signInAvailable: () => true,
}));

vi.mock("../app/lib/chat", () => ({
  streamChat: function* (...args: unknown[]) {
    streamChatMock(...args);
  },
}));

const { default: EvaluateForm } =
  await import("../app/components/evaluate-form");

afterEach(() => {
  cleanup();
  evaluateMock.mockReset();
  myTestMock.mockReset();
  streamChatMock.mockReset();
});

describe("reopening a stored test while a report is on screen", () => {
  it("gives the reopened report its own analyst, not the last one's", async () => {
    // The subtle one (117/#252, review): `show()` keeps the `done` phase, so
    // React reconciles `Report` in place. Without a key, `useAnalyst`'s refs
    // survive — the reopened report inherits the previous report's chat thread
    // and its transcript, and its own opening summary is never even asked for,
    // because `openedRef` is already true.
    evaluateMock.mockResolvedValue({ ...makeResponse(), status: "complete" });
    myTestMock.mockResolvedValue(OTHER);

    render(<EvaluateForm tracing={false} />);
    fireEvent.click(screen.getByRole("checkbox", { name: /japan/i }));
    fireEvent.change(screen.getByLabelText(/headline a/i), {
      target: { value: "Save 50% today" },
    });
    fireEvent.change(screen.getByLabelText(/headline b/i), {
      target: { value: "Members save half" },
    });
    fireEvent.click(screen.getByRole("button", { name: /evaluate/i }));

    await waitFor(() => expect(streamChatMock).toHaveBeenCalledTimes(1));
    const first = streamChatMock.mock.calls[0][0] as { threadId: string };

    fireEvent.click(await screen.findByText(/“Older line” vs “Its rival”/));

    // A second opening send, against a thread of its own.
    await waitFor(() => expect(streamChatMock).toHaveBeenCalledTimes(2));
    const second = streamChatMock.mock.calls[1][0] as {
      threadId: string;
      result: { variants: Record<string, string> };
    };
    expect(second.threadId).not.toBe(first.threadId);
    expect(second.result.variants).toEqual(OTHER.variants);
  });
});
