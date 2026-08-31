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
const replaceMock = vi.fn();

// The wizard learns which stored test to reopen from its address (119/#257):
// the rail lives in the shell now, and a row is a link to `/test?open=<id>`.
let search = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useSearchParams: () => search,
  useRouter: () => ({ replace: replaceMock, push: vi.fn() }),
}));

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
  replaceMock.mockReset();
  search = new URLSearchParams();
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

    const { rerender } = render(<EvaluateForm tracing={false} />);
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

    // The rail's link landed: same page, new address.
    search = new URLSearchParams("open=t-older");
    rerender(<EvaluateForm tracing={false} />);
    await waitFor(() => expect(myTestMock).toHaveBeenCalledWith("t-older"));

    // A second opening send, against a thread of its own.
    await waitFor(() => expect(streamChatMock).toHaveBeenCalledTimes(2));
    const second = streamChatMock.mock.calls[1][0] as {
      threadId: string;
      result: { variants: Record<string, string> };
    };
    expect(second.threadId).not.toBe(first.threadId);
    expect(second.result.variants).toEqual(OTHER.variants);
  });

  it("New test from a reopened report clears it back to the form", async () => {
    // Both the rail's rows and "New test" are links into the same route, so
    // Next reuses the mounted page: no remount, only the params change. The
    // wizard must treat losing `?open=` as the instruction it is.
    myTestMock.mockResolvedValue(OTHER);
    search = new URLSearchParams("open=t-older");
    const { rerender } = render(<EvaluateForm tracing={false} />);
    await screen.findByRole("button", { name: /test again/i });

    search = new URLSearchParams();
    rerender(<EvaluateForm tracing={false} />);

    expect(await screen.findByLabelText(/headline a/i)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /test again/i })).toBeNull();
  });

  it("says when a stored test cannot be opened, instead of a silent blank form", async () => {
    // The link can be stale — deleted in another tab — or the fetch can just
    // fail. Either way a wordless fall to the empty form reads as data loss:
    // the reader clicked a report they paid for and got nothing.
    myTestMock.mockRejectedValue(new Error("API responded 404"));
    search = new URLSearchParams("open=t-gone");
    render(<EvaluateForm tracing={false} />);

    expect(await screen.findByText(/could not be opened/i)).toBeTruthy();
  });
});
