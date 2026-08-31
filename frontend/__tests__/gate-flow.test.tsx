import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import EvaluateForm from "../app/components/evaluate-form";
import { makeResponse } from "./fixtures";

// 077/#167, decided 2026-08-31: pressing preview again after changing the form
// resumes the paused thread instead of starting a new run — a restart would
// re-run the paid, non-reproducible audience rewrite and could hand back a
// different reading than the one just rejected. Only changed audience *words*
// start fresh: rephrasing is a new reading. And the gate fires once per
// audience — an accepted reading rides later runs as `readingAccepted`, with
// the approved instruction, so the fifth headline variation is not a repaint
// of an approval already given.

const { evaluateMock, resumeMock } = vi.hoisted(() => ({
  evaluateMock: vi.fn(),
  resumeMock: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ replace: () => {}, push: () => {} }),
}));

vi.mock("../app/lib/api", () => ({
  evaluate: evaluateMock,
  resumeEvaluate: resumeMock,
  LOCALES: ["US", "JP", "DE"],
  MIN_PANEL_AGE: 18,
  MAX_PANEL_AGE: 100,
  myTests: () => Promise.resolve({ tests: [], next_cursor: null }),
  remainingRuns: () => Promise.resolve(3),
  myTest: () => Promise.reject(new Error("not used")),
  forgetTest: () => Promise.resolve(),
  onRunsChanged: () => () => {},
}));

vi.mock("../app/lib/auth", () => ({
  onAuthChange: (listener: (value: boolean) => void) => {
    listener(true);
    return () => {};
  },
  signInAvailable: () => false,
  mountGoogleButton: () => Promise.resolve(),
  signOut: () => Promise.resolve(),
}));

const RESPONSE = makeResponse();

const PAUSED = {
  status: "paused",
  thread_id: "t-1",
  preview: {
    query: {
      countries: ["JP"],
      coverage: "requested",
      min_age: 18,
      max_age: 100,
      gender: null,
      income_quintiles: [],
      education: [],
      traits: [],
      notices: [],
    },
    matched: 120,
    composition: {
      age_min: 22,
      age_median: 33,
      age_max: 48,
      countries: { JP: 5 },
      genders: { female: 3, male: 2 },
      education_levels: { secondary: 2, tertiary: 3 },
      income_bands: { lower: 1, middle: 3, upper: 1 },
    },
    notices: [],
    estimated_usd: 0.001,
    instruction: "You are a keen long-distance runner.",
    refusal_sentence: null,
  },
};

afterEach(() => {
  cleanup();
  evaluateMock.mockReset();
  resumeMock.mockReset();
});

async function fillAndSubmit(audience = "keen runners") {
  fireEvent.click(screen.getByRole("checkbox", { name: /japan/i }));
  fireEvent.change(screen.getByLabelText(/what are they like/i), {
    target: { value: audience },
  });
  fireEvent.change(screen.getByLabelText(/headline a/i), {
    target: { value: "Save 50% today" },
  });
  fireEvent.change(screen.getByLabelText(/headline b/i), {
    target: { value: "Members save half" },
  });
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: /evaluate/i }));
  });
}

async function backToTheForm() {
  await act(async () => {
    fireEvent.click(
      screen.getByRole("button", { name: /change the audience/i }),
    );
  });
}

describe("re-previewing while a run is paused", () => {
  it("resumes the paused thread with the form's controls and headlines", async () => {
    evaluateMock.mockResolvedValue(PAUSED);
    resumeMock.mockResolvedValue(PAUSED);
    render(<EvaluateForm tracing={false} />);
    await fillAndSubmit();
    await backToTheForm();

    // A control and a headline change on the form; the audience words do not.
    fireEvent.click(screen.getByRole("checkbox", { name: /united states/i }));
    fireEvent.change(screen.getByLabelText(/headline b/i), {
      target: { value: "Members save half price" },
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /evaluate/i }));
    });

    expect(evaluateMock).toHaveBeenCalledTimes(1);
    expect(resumeMock).toHaveBeenCalledTimes(1);
    const answer = resumeMock.mock.calls[0][0];
    expect(answer.threadId).toBe("t-1");
    expect(answer.action).toBe("adjust");
    expect(answer.query.countries).toEqual(
      expect.arrayContaining(["JP", "US"]),
    );
    expect(answer.headlineA).toBe("Save 50% today");
    expect(answer.headlineB).toBe("Members save half price");
  });

  it("starts fresh when the audience words themselves changed", async () => {
    evaluateMock.mockResolvedValue(PAUSED);
    render(<EvaluateForm tracing={false} />);
    await fillAndSubmit();
    await backToTheForm();

    fireEvent.change(screen.getByLabelText(/what are they like/i), {
      target: { value: "night-shift nurses" },
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /evaluate/i }));
    });

    // Rephrasing is a new reading: a second /evaluate, no resume.
    expect(evaluateMock).toHaveBeenCalledTimes(2);
    expect(resumeMock).not.toHaveBeenCalled();
  });

  it("falls back to a fresh run when the pause has expired", async () => {
    evaluateMock.mockResolvedValue(PAUSED);
    resumeMock.mockRejectedValue(
      new Error("this panel has expired — start the test again"),
    );
    render(<EvaluateForm tracing={false} />);
    await fillAndSubmit();
    await backToTheForm();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /evaluate/i }));
    });

    expect(resumeMock).toHaveBeenCalledTimes(1);
    expect(evaluateMock).toHaveBeenCalledTimes(2);
    expect(
      screen.getByRole("button", { name: /run the panel/i }),
    ).toBeDefined();
  });
});

describe("the gate fires once per audience", () => {
  it("skips the gate on a later run with the reading unchanged", async () => {
    evaluateMock.mockResolvedValueOnce(PAUSED);
    resumeMock.mockResolvedValue({ ...RESPONSE, status: "complete" });
    render(<EvaluateForm tracing={false} />);
    await fillAndSubmit();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /run the panel/i }));
    });
    await screen.findByRole("button", { name: /test again/i });

    // Same audience, new headline pair: the approval already given rides along.
    evaluateMock.mockResolvedValueOnce({ ...RESPONSE, status: "complete" });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /test again/i }));
    });
    fireEvent.change(screen.getByLabelText(/headline a/i), {
      target: { value: "A brand new line" },
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /evaluate/i }));
    });

    const request = evaluateMock.mock.calls[1][0];
    expect(request.readingAccepted).toBe(true);
    expect(request.instruction).toBe("You are a keen long-distance runner.");
  });

  it("echoes the accepted reading under the form, and Change re-arms the gate", async () => {
    evaluateMock.mockResolvedValue(PAUSED);
    resumeMock.mockResolvedValue({ ...RESPONSE, status: "complete" });
    render(<EvaluateForm tracing={false} />);
    await fillAndSubmit();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /run the panel/i }));
    });
    await screen.findByRole("button", { name: /test again/i });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /test again/i }));
    });

    // The echo names the reading and where it will be skipped.
    expect(screen.getByText(/read as/i)).toBeDefined();
    expect(screen.getByText(/5 seated/i)).toBeDefined();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^change$/i }));
    });
    expect(screen.queryByText(/read as/i)).toBeNull();

    // With the approval withdrawn, the next submit gates again.
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /evaluate/i }));
    });
    const request = evaluateMock.mock.calls[1][0];
    expect(request.readingAccepted ?? false).toBe(false);
  });

  it("gates again when a control changed since the approval", async () => {
    evaluateMock.mockResolvedValue(PAUSED);
    resumeMock.mockResolvedValue({ ...RESPONSE, status: "complete" });
    render(<EvaluateForm tracing={false} />);
    await fillAndSubmit();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /run the panel/i }));
    });
    await screen.findByRole("button", { name: /test again/i });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /test again/i }));
    });

    fireEvent.click(screen.getByRole("checkbox", { name: /germany/i }));
    // The echo withdraws on its own: the key no longer matches.
    expect(screen.queryByText(/read as/i)).toBeNull();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /evaluate/i }));
    });
    const request = evaluateMock.mock.calls[1][0];
    expect(request.readingAccepted ?? false).toBe(false);
  });

  it("rides a cleared instruction as a demographics-only run", async () => {
    // "" was the approval: demographics only after all. The skip-gate
    // contract requires an instruction whenever audience words ride, so the
    // honest translation is no words at all — the run is exactly what was
    // approved, and the validator has nothing to refuse.
    evaluateMock.mockResolvedValueOnce(PAUSED);
    resumeMock.mockResolvedValue({ ...RESPONSE, status: "complete" });
    render(<EvaluateForm tracing={false} />);
    await fillAndSubmit();
    fireEvent.change(screen.getByLabelText(/each panelist will be told/i), {
      target: { value: "" },
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /run the panel/i }));
    });
    await screen.findByRole("button", { name: /test again/i });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /test again/i }));
    });

    evaluateMock.mockResolvedValueOnce({ ...RESPONSE, status: "complete" });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /evaluate/i }));
    });

    const request = evaluateMock.mock.calls[1][0];
    expect(request.readingAccepted).toBe(true);
    expect(request.audience).toBe("");
    expect(request.instruction).toBeUndefined();
  });

  it("a live pause outranks the standing approval", async () => {
    // Accept, change a control (gates again), leave the gate, revert the
    // control: the key matches the approval again — but a run is holding at
    // the gate, and skipping past it would orphan the thread and buy a second
    // preview for the same test.
    evaluateMock.mockResolvedValue(PAUSED);
    resumeMock.mockResolvedValueOnce({ ...RESPONSE, status: "complete" });
    render(<EvaluateForm tracing={false} />);
    await fillAndSubmit();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /run the panel/i }));
    });
    await screen.findByRole("button", { name: /test again/i });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /test again/i }));
    });

    fireEvent.click(screen.getByRole("checkbox", { name: /germany/i }));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /evaluate/i }));
    });
    await backToTheForm();
    fireEvent.click(screen.getByRole("checkbox", { name: /germany/i }));

    resumeMock.mockResolvedValueOnce(PAUSED);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /evaluate/i }));
    });

    expect(resumeMock.mock.calls.at(-1)?.[0].action).toBe("adjust");
    // Two /evaluate calls in total: the first preview and the control-change
    // one — the revert rode the pause instead of starting a third.
    expect(evaluateMock).toHaveBeenCalledTimes(2);
  });

  it("surfaces a resume failure that is not a dead pause, instead of quietly paying again", async () => {
    evaluateMock.mockResolvedValue(PAUSED);
    resumeMock.mockRejectedValue(new Error("too many previews today"));
    render(<EvaluateForm tracing={false} />);
    await fillAndSubmit();
    await backToTheForm();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /evaluate/i }));
    });

    // One /evaluate: the original. The failed resume did not buy a rewrite.
    expect(evaluateMock).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/too many previews today/i)).toBeDefined();
  });
});
