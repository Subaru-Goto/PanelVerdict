import { afterEach, describe, expect, it, vi } from "vitest";

import {
  evaluate,
  forgetTest,
  onAccountChanged,
  resumeEvaluate,
} from "../app/lib/api";
import { RUN_BUDGET_SECONDS, RunTimedOut } from "../app/lib/run-budget";
import { makeResponse } from "./fixtures";

const RESPONSE = makeResponse();

const mockFetch = (status: number, body: object) => {
  const fetchMock = vi
    .fn()
    .mockResolvedValue(new Response(JSON.stringify(body), { status }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
};

afterEach(() => vi.unstubAllGlobals());

describe("evaluate", () => {
  it("sends the backend's exact wire fields and returns the parsed body", async () => {
    const fetchMock = mockFetch(200, RESPONSE);

    const result = await evaluate({
      target: { countries: ["JP"] },
      headlineA: "Save 50% today",
      headlineB: "Members save half",
    });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    // Same origin, exact path: the browser talks to its own proxy (045/#143),
    // which is the only holder of the edge secret.
    expect(url).toBe("/api/evaluate");
    // The exact keys EvaluateRequest requires — the missing target_description
    // is what made every submit a 422 before this slice.
    expect(JSON.parse(init.body as string)).toEqual({
      // The controls are the reading (094): structured, read by SQL, and the
      // retired target_description must never reappear — the backend forbids
      // unknown fields exactly so a stale bundle fails loudly.
      target: { countries: ["JP"] },
      headline_a: "Save 50% today",
      headline_b: "Members save half",
      // Nothing approved yet, so the panel gate stops this run.
      reading_accepted: false,
      // Blank audience is a real choice (demographics only) and costs no
      // model call — but it is still said, not implied.
      audience: "",
    });
    expect(result).toEqual(RESPONSE);
  });

  it("carries the audience words when the customer typed some", async () => {
    const fetchMock = mockFetch(200, RESPONSE);

    await evaluate({
      headlineA: "a",
      headlineB: "b",
      audience: "night-shift workers who commute by car",
    });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string).audience).toBe(
      "night-shift workers who commute by car",
    );
  });

  it("surfaces the backend's own refusal sentence as the error", async () => {
    mockFetch(402, {
      detail:
        "OpenRouter credit is exhausted and no vote was cast — rejected " +
        "requests are not charged. Top up and re-run: votes from earlier " +
        "runs are saved and resume free.",
    });

    await expect(evaluate({ headlineA: "a", headlineB: "b" })).rejects.toThrow(
      /Top up and re-run/,
    );
  });

  it("falls back to the status line when detail is not a string", async () => {
    // FastAPI's own validation errors carry a list-typed detail; forwarding a
    // serialized array would be noise, not a sentence.
    mockFetch(422, {
      detail: [{ loc: ["body", "headline_a"], msg: "required" }],
    });

    await expect(evaluate({ headlineA: "a", headlineB: "b" })).rejects.toThrow(
      "API responded 422",
    );
  });
});

describe("forgetTest", () => {
  it("announces that the account's figures changed once the row is gone", async () => {
    // The form's full-rail notice re-reads /me on this signal (124/#291): a
    // reader who deletes to make room should see the notice go, not linger.
    // A 204 carries no body, so the shared stub (which serialises one) is
    // the wrong shape here.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(null, { status: 204 })),
    );
    const listener = vi.fn();
    const stop = onAccountChanged(listener);

    await forgetTest("t-1");
    stop();

    expect(listener).toHaveBeenCalledTimes(1);
    expect(listener).toHaveBeenCalledWith("delete");
  });

  it("does not announce a delete the server refused", async () => {
    mockFetch(500, {});
    const listener = vi.fn();
    const stop = onAccountChanged(listener);

    await expect(forgetTest("t-1")).rejects.toThrow();
    stop();

    expect(listener).not.toHaveBeenCalled();
  });
});

// 032/#133: the one deadline the run has, mirrored on the client so a dead
// connection cannot outlive the proxy's budget.
describe("the run's deadline", () => {
  afterEach(() => vi.useRealTimers());

  const signalOf = (fetchMock: ReturnType<typeof vi.fn>): AbortSignal => {
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    return init.signal as AbortSignal;
  };

  // A fetch that behaves like the browser's: pending until its signal fires,
  // then rejecting with the signal's reason.
  const hangingFetch = () =>
    vi.fn().mockImplementation(
      (_url: string, init: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          const signal = init.signal as AbortSignal;
          signal.addEventListener("abort", () => reject(signal.reason));
        }),
    );

  it("evaluate carries a signal that fires at the budget, not before", async () => {
    vi.useFakeTimers();
    const fetchMock = hangingFetch();
    vi.stubGlobal("fetch", fetchMock);
    const run = evaluate({ headlineA: "a", headlineB: "b" });
    await vi.advanceTimersByTimeAsync(0);

    const signal = signalOf(fetchMock);
    await vi.advanceTimersByTimeAsync(RUN_BUDGET_SECONDS * 1000 - 1);
    expect(signal.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    expect(signal.aborted).toBe(true);
    await expect(run).rejects.toBeInstanceOf(RunTimedOut);
  });

  it("resumeEvaluate carries the same signal", async () => {
    vi.useFakeTimers();
    const fetchMock = hangingFetch();
    vi.stubGlobal("fetch", fetchMock);
    const run = resumeEvaluate({ threadId: "t", action: "accept" });
    await vi.advanceTimersByTimeAsync(RUN_BUDGET_SECONDS * 1000);

    expect(signalOf(fetchMock).aborted).toBe(true);
    await expect(run).rejects.toBeInstanceOf(RunTimedOut);
  });

  it("a fetch the deadline aborted is a RunTimedOut", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new DOMException("aborted", "TimeoutError")),
    );

    await expect(
      evaluate({ headlineA: "a", headlineB: "b" }),
    ).rejects.toBeInstanceOf(RunTimedOut);
  });

  it("a 504 after the budget is the deadline; one before it is a plain API error", async () => {
    vi.useFakeTimers();
    const late = vi.fn().mockImplementation(
      () =>
        new Promise<Response>((resolve) => {
          setTimeout(
            () => resolve(new Response(null, { status: 504 })),
            RUN_BUDGET_SECONDS * 1000,
          );
        }),
    );
    vi.stubGlobal("fetch", late);
    const timedOut = evaluate({ headlineA: "a", headlineB: "b" });
    await vi.advanceTimersByTimeAsync(RUN_BUDGET_SECONDS * 1000);
    await expect(timedOut).rejects.toBeInstanceOf(RunTimedOut);

    mockFetch(504, {});
    await expect(evaluate({ headlineA: "a", headlineB: "b" })).rejects.toThrow(
      "API responded 504",
    );
  });
});
