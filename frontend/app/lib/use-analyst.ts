"use client";

import { useRef, useState } from "react";

import type { EvaluateResponse } from "./api";
import { streamChat } from "./chat";

export type AnalystReply = {
  role: "analyst";
  text: string;
  /** What the analyst is doing right now — the tool front edge. Cleared the
   *  moment the first token arrives. */
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

export function useAnalyst(result: EvaluateResponse) {
  // Minted client-side, once per mounted report: the server treats an unseen
  // id as a fresh conversation, so no registration round-trip exists.
  const threadIdRef = useRef<string | null>(null);
  const threadId = (threadIdRef.current ??= crypto.randomUUID());

  const [turns, setTurns] = useState<AnalystTurn[]>([]);
  const [busy, setBusy] = useState(false);

  const patchReply = (patch: (reply: AnalystReply) => Partial<AnalystReply>) =>
    setTurns((current) =>
      current.map((turn, index) =>
        index === current.length - 1 && turn.role === "analyst"
          ? { ...turn, ...patch(turn) }
          : turn,
      ),
    );

  async function send(message: string): Promise<void> {
    const text = message.trim();
    if (busy || text === "") return;
    setBusy(true);
    setTurns((current) => [
      ...current,
      { role: "user", text },
      { role: "analyst", text: "", status: null, error: null },
    ]);
    // `done` is what separates a finished turn from a dropped connection —
    // a stream can end cleanly at the transport level and still be truncated.
    let terminal = false;
    try {
      for await (const event of streamChat({
        threadId,
        message: text,
        result,
      })) {
        switch (event.type) {
          case "tool":
            patchReply(() => ({
              status: TOOL_STATUS[event.name] ?? "Working…",
            }));
            break;
          case "token":
            patchReply((reply) => ({
              text: reply.text + event.text,
              status: null,
            }));
            break;
          case "error":
            patchReply(() => ({ error: event.message, status: null }));
            terminal = true;
            break;
          case "done":
            terminal = true;
            break;
        }
      }
    } catch (error) {
      patchReply(() => ({
        error:
          error instanceof Error ? error.message : "The request failed.",
        status: null,
      }));
      terminal = true;
    }
    if (!terminal) {
      patchReply(() => ({
        error: "The connection was lost before the answer finished.",
        status: null,
      }));
    }
    setBusy(false);
  }

  return { turns, busy, send };
}
