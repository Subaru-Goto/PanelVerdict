"use client";

import { useState } from "react";

import { evaluate, type EvaluateInput, type EvaluateResponse } from "./api";

/** The request's four phases as one value, so contradictory combinations —
 *  loading with a stale result, an error beside a success — cannot be
 *  represented, only replaced. */
export type EvaluateState =
  | { phase: "idle" }
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "done"; result: EvaluateResponse };

export function useEvaluate() {
  const [state, setState] = useState<EvaluateState>({ phase: "idle" });

  async function submit(request: EvaluateInput): Promise<void> {
    setState({ phase: "loading" });
    try {
      setState({ phase: "done", result: await evaluate(request) });
    } catch (error) {
      setState({
        phase: "error",
        message: error instanceof Error ? error.message : "Request failed",
      });
    }
  }

  return { state, submit };
}
