"use client";

import { useRef, useState } from "react";

import type { EvaluateResponse } from "./api";
import { streamChat } from "./chat";

export type AnalystReply = {
  role: "analyst";
  text: string;
  /** What the analyst is doing right now — "Thinking…" from the first
   *  instant, a tool's sentence while one runs, cleared by the first token. */
  status: string | null;
  error: string | null;
};

export type AnalystTurn = { role: "user"; text: string } | AnalystReply;

/** The dock never shows a raw tool name; it says what the wait feels like.
 *  An unknown name (a tool added later) degrades to the generic sentence. */
const TOOL_STATUS: Record<string, string> = {
  analyze_results: "Checking the numbers…",
  search_personas: "Looking through the panel…",
  run_panel_test: "Running a new panel test — this can take minutes…",
};

/** Reveal pacing: ~3 characters per 16ms tick ≈ 180 chars/second. Feel
 *  constants tuned by eye, not derived — the model writes faster than a
 *  human reads, so even a genuine stream lands as a paste without this. */
const REVEAL_TICK_MS = 16;
const REVEAL_CHARS_PER_TICK = 3;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export function useAnalyst(result: EvaluateResponse) {
  // Minted client-side, once per mounted report: the server treats an unseen
  // id as a fresh conversation, so no registration round-trip exists.
  const threadIdRef = useRef<string | null>(null);
  const threadId = (threadIdRef.current ??= crypto.randomUUID());

  const [turns, setTurns] = useState<AnalystTurn[]>([]);
  const [busy, setBusy] = useState(false);

  async function send(message: string): Promise<void> {
    const text = message.trim();
    if (busy || text === "") return;
    setBusy(true);

    // Fixed for the whole turn: `busy` blocks a second send, so nothing else
    // can grow the transcript while this one streams.
    const history: AnalystTurn[] = [...turns, { role: "user", text }];

    // Plain variables accumulate; paint() renders the current snapshot.
    // `received` is what the stream has delivered, `shown` how much of it
    // the reader has been shown — the gap between them is the typewriter.
    let received = "";
    let shown = 0;
    let status: string | null = "Thinking…";
    let error: string | null = null;

    const paint = () =>
      setTurns([
        ...history,
        { role: "analyst", text: received.slice(0, shown), status, error },
      ]);
    paint();

    // Reveals while the stream is still arriving — a long answer types from
    // its first token, it does not wait for the last.
    const reveal = setInterval(() => {
      if (shown < received.length) {
        shown = Math.min(received.length, shown + REVEAL_CHARS_PER_TICK);
        paint();
      }
    }, REVEAL_TICK_MS);

    // `done` is what separates a finished turn from a dropped connection —
    // a stream can end cleanly at the transport level and still be truncated.
    let finished = false;
    try {
      for await (const event of streamChat({ threadId, message: text, result })) {
        switch (event.type) {
          case "tool":
            status = TOOL_STATUS[event.name] ?? "Working…";
            break;
          case "token":
            received += event.text;
            status = null;
            break;
          case "error":
            error = event.message;
            status = null;
            finished = true;
            break;
          case "done":
            finished = true;
            break;
        }
        paint();
      }
    } catch (caught) {
      error = caught instanceof Error ? caught.message : "The request failed.";
      status = null;
      finished = true;
    }
    if (!finished) {
      error = "The connection was lost before the answer finished.";
      status = null;
    }

    // Let the typewriter catch up before unlocking the input — the stream
    // usually ends long before a reader could have kept up with it.
    while (shown < received.length) {
      await sleep(REVEAL_TICK_MS);
    }
    clearInterval(reveal);
    paint();
    setBusy(false);
  }

  return { turns, busy, send };
}
