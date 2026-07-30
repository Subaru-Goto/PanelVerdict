"use client";

import { useEffect, useRef, useState } from "react";

import type { EvaluateResponse } from "./api";
import { streamChat } from "./chat";

export type AnalystReply = {
  role: "analyst";
  text: string;
  /** What the analyst is doing right now — "Thinking…" from the first
   *  instant, a tool's sentence while one runs, cleared once the reader can
   *  actually see text arriving. */
  status: string | null;
  error: string | null;
};

/** The question the report asks on the reader's behalf, so the page opens with
 *  a reading of the panel rather than 25 raw reasons. Exported because the dock
 *  has to tell it apart from something the reader actually typed. */
export const OPENING_REQUEST =
  "Summarise what the panel said and why they said it, in a short paragraph.";

export type AnalystTurn = { role: "user"; text: string } | AnalystReply;

/** The opening turn is the report's question, not the reader's — so the dock
 *  neither prints it as their message nor counts it as them having started the
 *  conversation. One predicate, because both readings must agree. */
export const isOpeningRequest = (turn: AnalystTurn): boolean =>
  turn.role === "user" && turn.text === OPENING_REQUEST;

/** The dock never shows a raw tool name; it says what the wait feels like.
 *  An unknown name (a tool added later) degrades to the generic sentence. */
const TOOL_STATUS: Record<string, string> = {
  analyze_results: "Checking the numbers…",
  search_personas: "Looking through the panel…",
  read_reasons: "Reading what the panel said…",
  run_panel_test: "Running a new panel test — this can take minutes…",
};

/** One tick per frame at 60Hz — the browser's own repaint budget. */
const REVEAL_TICK_MS = 16;
/** PENDING USER SIGN-OFF (not yet approved): reveal speed is a feel
 *  parameter with no derivation — it needs judging in a browser, not in a
 *  test. Placeholder until then. */
const REVEAL_CHARS_PER_SECOND = 180;

/** One conversation, shared: the report renders its opening turn as a summary
 *  and the dock continues the same thread, so a follow-up resolves against
 *  words already in the transcript instead of re-buying the tool calls. */
export type Analyst = {
  turns: AnalystTurn[];
  busy: boolean;
  send: (message: string) => Promise<void>;
};

export function useAnalyst(
  result: EvaluateResponse,
  opening?: string,
): Analyst {
  // Minted client-side, once per mounted report: the server treats an unseen
  // id as a fresh conversation, so no registration round-trip exists.
  const threadIdRef = useRef<string | null>(null);
  const threadId = (threadIdRef.current ??= crypto.randomUUID());

  const [turns, setTurns] = useState<AnalystTurn[]>([]);
  const [busy, setBusy] = useState(false);

  // A ref, not the `busy` state: two clicks landing in one frame both read
  // the same pre-render `busy === false` and would both open a turn, each
  // painting over the other's transcript.
  const busyRef = useRef(false);
  // The dock unmounts mid-stream whenever a new evaluate starts, so the
  // reveal timer has to be reachable from cleanup.
  const goneRef = useRef(false);
  const revealRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    // Set on every setup, not just at `useRef`'s initial value: refs survive
    // React's dev-only mount→cleanup→mount, so a cleanup-only effect leaves
    // this stuck true for the component's whole life — which froze the dock
    // in dev while the suite, which renders without StrictMode, stayed green.
    goneRef.current = false;
    return () => {
      goneRef.current = true;
      if (revealRef.current !== null) clearInterval(revealRef.current);
    };
  }, []);

  // Deliberately never reset in a setup, unlike `goneRef` above: this asks
  // "has this thread ever been opened", and a ref surviving React's dev-only
  // remount is precisely what stops one conversation becoming two paid ones.
  // The property that made `goneRef` a bug is the one that fixes this.
  const openedRef = useRef(false);

  useEffect(() => {
    if (opening === undefined || openedRef.current) return;
    // Deferred a tick, and cancelled by the cleanup, so the send never begins
    // inside a mount React is about to discard: the simulated unmount would
    // clear that send's reveal timer while its stream kept arriving, leaving
    // an answer that was received and never shown. The flag is set when the
    // send fires rather than when it is scheduled, so the cancelled attempt
    // does not count as having opened the thread.
    const scheduled = setTimeout(() => {
      openedRef.current = true;
      void send(opening);
    }, 0);
    return () => clearTimeout(scheduled);
    // `send` is intentionally absent: it is redefined every render, the flag
    // above makes a re-run a no-op, and listing it would restart the opening
    // turn on every keystroke in the composer.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opening]);

  async function send(message: string): Promise<void> {
    const text = message.trim();
    if (busyRef.current || text === "") return;
    busyRef.current = true;
    setBusy(true);

    const history: AnalystTurn[] = [...turns, { role: "user", text }];

    // `received` is everything the stream has delivered, `shown` how much of
    // it the reader has been given — the gap between them is the typewriter.
    let received = "";
    let shown = 0;
    let status: string | null = "Thinking…";
    let error: string | null = null;
    let streamed = false;

    const paint = () => {
      if (goneRef.current) return;
      setTurns([
        ...history,
        { role: "analyst", text: received.slice(0, shown), status, error },
      ]);
    };
    paint();

    // Paced by the clock rather than by tick count: a background tab throttles
    // setInterval to about 1s, and counting characters per tick would stretch
    // a long answer into minutes with the composer still locked.
    const revealed = new Promise<void>((resolve) => {
      let tickedAt = Date.now();
      const timer = setInterval(() => {
        const now = Date.now();
        const budget = ((now - tickedAt) * REVEAL_CHARS_PER_SECOND) / 1000;
        tickedAt = now;
        if (goneRef.current) {
          clearInterval(timer);
          resolve();
          return;
        }
        if (shown < received.length) {
          shown = Math.min(received.length, shown + Math.ceil(budget));
          // Cleared here rather than on arrival: the wait is over when the
          // reader can see the answer, not when the socket saw it.
          status = null;
          paint();
        }
        if (streamed && shown >= received.length) {
          clearInterval(timer);
          resolve();
        }
      }, REVEAL_TICK_MS);
      revealRef.current = timer;
    });

    // `done` is what separates a finished turn from a dropped connection —
    // a stream can end cleanly at the transport level and still be truncated.
    let finished = false;
    try {
      for await (const event of streamChat({ threadId, message: text, result })) {
        if (goneRef.current) break;
        switch (event.type) {
          case "tool":
            status = TOOL_STATUS[event.name] ?? "Working…";
            break;
          case "token":
            received += event.text;
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
    streamed = true;

    // The stream ends long before a reader could have kept up with it, so the
    // composer unlocks when the typewriter does, not when the socket closes.
    await revealed;
    revealRef.current = null;
    paint();
    busyRef.current = false;
    if (!goneRef.current) setBusy(false);
  }

  return { turns, busy, send };
}
