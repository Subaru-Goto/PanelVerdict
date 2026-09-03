import { authHeaders } from "./auth";

/** One NDJSON line of the streaming /chat response — the TypeScript mirror of
 *  the backend's ChatStreamEvent union, discriminated the same way so a
 *  `switch (event.type)` narrows each arm to exactly its own fields. */
export type ToolEvent = { type: "tool"; name: string };
export type TokenEvent = { type: "token"; text: string };
/** Terminal and in-band: a stream commits its HTTP status at the first byte,
 *  so failures after that arrive here, never as a status code. */
export type ErrorEvent = { type: "error"; message: string };
/** What tells a completed turn apart from a dropped connection. */
export type DoneEvent = { type: "done" };
export type ChatStreamEvent = ToolEvent | TokenEvent | ErrorEvent | DoneEvent;

/** The test travels as its id (035/#136): the server reads its own stored
 *  copy under the signed-in account, so the analyst's scope is what the run
 *  wrote, never what this page holds. */
export type ChatInput = {
  threadId: string;
  testId: string;
  message: string;
};

/** One turn of the analyst, event by event, while the model is still writing.
 *
 *  fetch + ReadableStream rather than EventSource, because EventSource cannot
 *  POST. The network delivers bytes, not lines: chunks are buffered and split
 *  on newline, and a partial trailing line waits for its next chunk. A stream
 *  that ends mid-line is a dropped connection — the unfinished line is
 *  discarded, and the missing `done` event is what tells the caller.
 */
export async function* streamChat(
  input: ChatInput,
): AsyncGenerator<ChatStreamEvent> {
  // Same origin, through the proxy route (045/#143); the stream pipes through.
  // Signed in like the run is (063/#158): the analyst spends money too, so it
  // is gated by the same verified identity rather than left as the cheap way
  // in.
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify({
      thread_id: input.threadId,
      test_id: input.testId,
      message: input.message,
    }),
  });
  if (!res.ok || res.body === null) {
    // The 422 guard and the 400 pre-flight refusal fire before the stream
    // starts — the last moment the backend can speak through a status code —
    // and their detail is safe by construction (fixed sentences, never
    // provider or classifier text).
    const body = (await res.json().catch(() => null)) as {
      detail?: string;
    } | null;
    throw new Error(
      typeof body?.detail === "string"
        ? body.detail
        : `API responded ${res.status}`,
    );
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) return;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (line !== "") yield JSON.parse(line) as ChatStreamEvent;
    }
  }
}
