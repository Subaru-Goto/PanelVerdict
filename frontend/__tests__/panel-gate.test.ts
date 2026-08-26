import { afterEach, describe, expect, it, vi } from "vitest";

import {
  evaluate,
  resumeEvaluate,
  type TargetQuery,
} from "../app/lib/api";

// 076/#166. `/evaluate` no longer always answers with a verdict: a first run
// stops at the panel gate and answers with the panel it would seat. What is
// pinned here is that the browser can tell the two apart and can answer the
// gate — the *shape* of the contract, not the screen it eventually becomes
// (093/#198 owns that).

vi.mock("../app/lib/auth", () => ({ authHeaders: vi.fn().mockResolvedValue({}) }));

afterEach(() => vi.unstubAllGlobals());

const INPUT = { headlineA: "a", headlineB: "b" };

const QUERY: TargetQuery = {
  countries: ["JP"],
  coverage: "requested",
  min_age: 18,
  max_age: 100,
  gender: null,
  income_quintiles: [],
  education: [],
  traits: [],
  notices: [],
};

const PREVIEW = {
  query: QUERY,
  matched: 5,
  composition: { age_min: 20, age_median: 30, age_max: 40 },
  notices: [],
  estimated_usd: 0.001,
};

function stub(body: unknown) {
  const fetcher = vi
    .fn()
    .mockResolvedValue(new Response(JSON.stringify(body), { status: 200 }));
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}

describe("a run that stops at the gate", () => {
  it("is reported as paused rather than mistaken for a verdict", async () => {
    stub({ status: "paused", thread_id: "t-1", preview: PREVIEW });

    const outcome = await evaluate(INPUT);

    expect(outcome.status).toBe("paused");
    if (outcome.status !== "paused") throw new Error("unreachable");
    expect(outcome.preview.matched).toBe(5);
    expect(outcome.thread_id).toBe("t-1");
  });

  it("says the audience was already approved when it was", async () => {
    // The gate fires on the first run and whenever the audience changes — so
    // the client has to be able to say it has already seen this one.
    const fetcher = stub({ status: "complete", counts: { voted: 5 } });

    await evaluate({ ...INPUT, readingAccepted: true });

    const [, init] = fetcher.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body)).reading_accepted).toBe(true);
  });
});

describe("answering the gate", () => {
  it("accepts, and gets the verdict", async () => {
    const fetcher = stub({ status: "complete", counts: { voted: 5 } });

    const outcome = await resumeEvaluate({ threadId: "t-1", action: "accept" });

    const [url, init] = fetcher.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/evaluate/resume");
    expect(JSON.parse(String(init.body))).toEqual({
      thread_id: "t-1",
      action: "accept",
    });
    expect(outcome.status).toBe("complete");
  });

  it("sends an edited reading when adjusting", async () => {
    const fetcher = stub({ status: "paused", thread_id: "t-1", preview: PREVIEW });

    await resumeEvaluate({
      threadId: "t-1",
      action: "adjust",
      query: QUERY,
    });

    const [, init] = fetcher.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body)).query).toEqual(QUERY);
  });

  it("sends an untouched draft as absence and an edit as itself", async () => {
    // None and "" are different answers (094/#200): absence means the reader
    // left the generated sentence alone, so no check is charged; "" means
    // "demographics only after all", and is a real, checkable answer.
    const body = { status: "paused", thread_id: "t-1", preview: PREVIEW };
    const fetcher = vi
      .fn()
      .mockImplementation(() =>
        Promise.resolve(new Response(JSON.stringify(body), { status: 200 })),
      );
    vi.stubGlobal("fetch", fetcher);

    await resumeEvaluate({ threadId: "t-1", action: "accept" });
    await resumeEvaluate({
      threadId: "t-1",
      action: "accept",
      instruction: "You are a keen runner.",
    });
    await resumeEvaluate({ threadId: "t-1", action: "accept", instruction: "" });

    const bodies = fetcher.mock.calls.map((call) =>
      JSON.parse(String((call[1] as RequestInit).body)),
    );
    expect("instruction" in bodies[0]).toBe(false);
    expect(bodies[1].instruction).toBe("You are a keen runner.");
    expect(bodies[2].instruction).toBe("");
  });

  it("carries the session, because the resume spends the money", async () => {
    stub({ status: "complete", counts: { voted: 5 } });

    await resumeEvaluate({ threadId: "t-1", action: "accept" });

    // authHeaders is mocked empty here; what matters is that it was consulted
    // rather than the resume going out unauthenticated by construction.
    const { authHeaders } = await import("../app/lib/auth");
    expect(authHeaders).toHaveBeenCalled();
  });
});
