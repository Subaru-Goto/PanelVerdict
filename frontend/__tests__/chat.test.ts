import { afterEach, describe, expect, it, vi } from "vitest";

import { streamChat, type ChatStreamEvent } from "../app/lib/chat";

/** A Response whose body arrives in exactly these chunks — the boundary every
 *  NDJSON reader has to survive is a JSON line split mid-object. */
const streamingResponse = (...chunks: string[]) => {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(body, { status: 200 });
};

const mockFetch = (response: Response) => {
  const fetchMock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
};

const collect = async (): Promise<ChatStreamEvent[]> => {
  const events: ChatStreamEvent[] = [];
  for await (const event of streamChat({
    threadId: "t-1",
    testId: "test-9",
    message: "Why did it stop early?",
  })) {
    events.push(event);
  }
  return events;
};

afterEach(() => vi.unstubAllGlobals());

describe("streamChat", () => {
  it("sends the backend's exact wire fields", async () => {
    const fetchMock = mockFetch(streamingResponse('{"type":"done"}\n'));

    await collect();

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    // Same origin, exact path: the stream flows through the proxy (045/#143).
    expect(url).toBe("/api/chat");
    // The test travels as its id, never as its report (035/#136).
    expect(JSON.parse(init.body as string)).toEqual({
      thread_id: "t-1",
      test_id: "test-9",
      message: "Why did it stop early?",
    });
  });

  it("yields every event of a multi-line chunk, in order", async () => {
    mockFetch(
      streamingResponse(
        '{"type":"tool","name":"analyze_results"}\n' +
          '{"type":"token","text":"The interval "}\n' +
          '{"type":"token","text":"cleared the band."}\n' +
          '{"type":"done"}\n',
      ),
    );

    expect(await collect()).toEqual([
      { type: "tool", name: "analyze_results" },
      { type: "token", text: "The interval " },
      { type: "token", text: "cleared the band." },
      { type: "done" },
    ]);
  });

  it("reassembles a JSON line split across chunk boundaries", async () => {
    // The network owes us bytes, not lines: this token line arrives in three
    // pieces, one of them mid-word.
    mockFetch(
      streamingResponse(
        '{"type":"token",',
        '"text":"pie',
        'ces"}\n{"type":"done"}\n',
      ),
    );

    expect(await collect()).toEqual([
      { type: "token", text: "pieces" },
      { type: "done" },
    ]);
  });

  it("throws the backend's own refusal sentence on a pre-stream 404", async () => {
    // A test that is not this account's, or is gone: the tests endpoint's
    // own sentence, before any stream.
    mockFetch(
      new Response(JSON.stringify({ detail: "no such test" }), { status: 404 }),
    );

    await expect(collect()).rejects.toThrow(/no such test/);
  });
});
