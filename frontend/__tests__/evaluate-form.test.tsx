import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import EvaluateForm from "../app/components/evaluate-form";
import { makeResponse } from "./fixtures";

const { evaluateMock, resumeMock } = vi.hoisted(() => ({
  evaluateMock: vi.fn(),
  resumeMock: vi.fn(),
}));

vi.mock("../app/lib/api", () => ({
  evaluate: evaluateMock,
  resumeEvaluate: resumeMock,
}));

const RESPONSE = makeResponse();

afterEach(() => {
  cleanup();
  evaluateMock.mockReset();
  resumeMock.mockReset();
});

async function fillAndSubmit() {
  fireEvent.click(screen.getByRole("checkbox", { name: /japan/i }));
  fireEvent.change(screen.getByLabelText(/headline a/i), {
    target: { value: "Save 50% today" },
  });
  fireEvent.change(screen.getByLabelText(/headline b/i), {
    target: { value: "Members save half" },
  });
  fireEvent.click(screen.getByRole("button", { name: /evaluate/i }));
}

describe("EvaluateForm", () => {
  it("discloses the AI system on the form, before anything is submitted", () => {
    // Submitting headlines to a synthetic panel is interacting with an AI
    // system, so the disclosure rides with the submit control — told before
    // the exchange, not in a footer after it.
    render(<EvaluateForm />);

    expect(screen.getByText(/PanelVerdict is an AI system/)).toBeTruthy();
  });

  it("says nothing about tracing when this deployment is not tracing", () => {
    // The default, and the one that must not over-warn: a page claiming the
    // reader's unreleased copy leaves our infrastructure, when it does not,
    // is as much a false statement as the silence in the other direction.
    render(<EvaluateForm tracing={false} />);

    expect(screen.queryByText(/traced for debugging/i)).toBeNull();
  });

  it("discloses tracing on the form when this deployment traces", () => {
    // A reader's input can be unreleased marketing copy, so the telling
    // belongs beside the input where it can still change what they type —
    // not in a policy page after the fact.
    render(<EvaluateForm tracing />);

    expect(screen.getByText(/traced for debugging/i)).toBeTruthy();
  });

  it("runs on headlines alone — the audience is optional", () => {
    // Two headlines against a cross-section of the whole pool is the simplest
    // thing the product does, and the gate here was the only reason it could
    // not be asked for. The previous version of this test asserted the bug.
    evaluateMock.mockResolvedValue(RESPONSE);
    render(<EvaluateForm />);
    const button = screen.getByRole("button", { name: /evaluate/i });

    expect(button.hasAttribute("disabled")).toBe(true);
    fireEvent.change(screen.getByLabelText(/headline a/i), {
      target: { value: "Save 50% today" },
    });
    fireEvent.change(screen.getByLabelText(/headline b/i), {
      target: { value: "Members save half" },
    });

    expect(button.hasAttribute("disabled")).toBe(false);
    fireEvent.click(button);
    expect(evaluateMock).toHaveBeenCalledWith(
      expect.objectContaining({
        target: expect.objectContaining({ countries: [] }),
        audience: "",
        headlineA: "Save 50% today",
        headlineB: "Members save half",
      }),
    );
  });

  it("sends the controls and both headlines to evaluate", async () => {
    evaluateMock.mockResolvedValue(RESPONSE);
    render(<EvaluateForm />);

    await fillAndSubmit();

    expect(evaluateMock).toHaveBeenCalledWith(
      expect.objectContaining({
        target: expect.objectContaining({ countries: ["JP"] }),
        headlineA: "Save 50% today",
        headlineB: "Members save half",
      }),
    );
  });

  it("offers the four controls and no free-text target", () => {
    // Demographics come from controls because controls cannot be misread
    // (094): country, age, gender, education, income — and the retired
    // description field must not quietly survive.
    render(<EvaluateForm />);

    expect(screen.queryByLabelText(/who should judge/i)).toBeNull();
    expect(screen.getByRole("checkbox", { name: /japan/i })).toBeTruthy();
    expect(screen.getByLabelText(/age from/i)).toBeTruthy();
    expect(screen.getByLabelText(/age to/i)).toBeTruthy();
    expect(screen.getByLabelText(/gender/i)).toBeTruthy();
    expect(screen.getByRole("checkbox", { name: /tertiary/i })).toBeTruthy();
    expect(screen.getByRole("checkbox", { name: /q1/i })).toBeTruthy();
  });

  it("renders notices with warnings distinguishable from readings", async () => {
    evaluateMock.mockResolvedValue(RESPONSE);
    render(<EvaluateForm />);

    await fillAndSubmit();

    const warning = await screen.findByText(/did not vote/);
    const reading = screen.getByText(/Stopped after 50/);
    expect(warning.className).toContain("border-red");
    expect(reading.className).not.toContain("border-red");
  });

  it("renders the counts and says an early stop is an answer", async () => {
    evaluateMock.mockResolvedValue(RESPONSE);
    render(<EvaluateForm />);

    await fillAndSubmit();

    expect(
      await screen.findByText(/50 of 200 matched panelists voted/),
    ).toBeTruthy();
    expect(
      screen.getByText(/stopped early: the call was already clear/),
    ).toBeTruthy();
  });

  it("renders model output as literal text, never as markup", async () => {
    // The exfiltration defense: a reason carrying HTML must
    // reach the reader as characters. If this ever renders a <b> element, model
    // output has found a markup sink.
    evaluateMock.mockResolvedValue(RESPONSE);
    const { container } = render(<EvaluateForm />);

    await fillAndSubmit();

    expect(
      await screen.findByText(/<b>50% off<\/b> is the only thing/),
    ).toBeTruthy();
    expect(container.querySelector("b")).toBeNull();
  });
});

describe("coverage", () => {
  it("shows which countries the panel was drawn from", async () => {
    evaluateMock.mockResolvedValue(RESPONSE);
    render(<EvaluateForm />);

    await fillAndSubmit();

    expect(await screen.findByText("US")).toBeTruthy();
    expect(screen.getByText("JP")).toBeTruthy();
    expect(screen.getByText("DE")).toBeTruthy();
  });

  it("names the stand-in when a region was approximated", async () => {
    const base = makeResponse();
    evaluateMock.mockResolvedValue({
      ...base,
      query: { ...base.query, coverage: "approximated" as const },
    });
    render(<EvaluateForm />);

    await fillAndSubmit();

    expect(await screen.findByText(/stand-in region was used/)).toBeTruthy();
  });

  it("says plainly when the panel carries no geographic targeting", async () => {
    // Unmatched coverage resolves to the whole pool,
    // byte-identical to a deliberate global panel — only this flag can tell
    // the customer the difference, so it must sit with the verdict.
    evaluateMock.mockResolvedValue({
      ...RESPONSE,
      query: { ...RESPONSE.query, coverage: "unmatched" as const },
    });
    render(<EvaluateForm />);

    await fillAndSubmit();

    const flag = await screen.findByText(/no geographic targeting/);
    expect(flag.className).toContain("text-red");
  });
});

describe("after a run", () => {
  it("puts the report where the form was, behind a Test again", async () => {
    // The form is scaffolding for asking a question; once it is answered the
    // reader wants the answer at the top, not to scroll past the inputs.
    evaluateMock.mockResolvedValue(RESPONSE);
    render(<EvaluateForm />);

    await fillAndSubmit();
    await screen.findByRole("button", { name: /test again/i });

    expect(screen.queryByLabelText(/headline a/i)).toBeNull();
  });

  it("returns to the form with the answers still in it", async () => {
    // Changing one headline is the common second run, so a blank form would
    // make the reader retype the two fields they meant to keep.
    evaluateMock.mockResolvedValue(RESPONSE);
    render(<EvaluateForm />);

    await fillAndSubmit();
    fireEvent.click(await screen.findByRole("button", { name: /test again/i }));

    expect(
      (screen.getByLabelText(/headline a/i) as HTMLInputElement).value,
    ).toBe("Save 50% today");
  });
});

describe("request lifecycle", () => {
  it("keeps submit disabled while a run is in flight", async () => {
    evaluateMock.mockReturnValue(new Promise(() => {}));
    render(<EvaluateForm />);

    await fillAndSubmit();

    const button = screen.getByRole("button", { name: /asking the panel/i });
    expect(button.hasAttribute("disabled")).toBe(true);
  });

  it("shows the backend's refusal sentence when the run fails", async () => {
    evaluateMock.mockRejectedValue(
      new Error("OpenRouter credit is exhausted and no vote was cast."),
    );
    render(<EvaluateForm />);

    await fillAndSubmit();

    expect(
      await screen.findByText(/Error: OpenRouter credit is exhausted/),
    ).toBeTruthy();
  });
});

describe("while the panel is voting", () => {
  it("keeps proving it is alive rather than looking frozen", async () => {
    // The complaint this answers: a long run and a dead one looked identical,
    // because a disabled button is the same pixels either way. A number that
    // moves is proof of life that costs the backend nothing.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      evaluateMock.mockReturnValue(new Promise(() => {}));
      render(<EvaluateForm />, { wrapper: StrictMode });
      await fillAndSubmit();

      const status = screen.getByRole("status");
      expect(status.textContent).toContain("0s");

      await act(async () => {
        await vi.advanceTimersByTimeAsync(3000);
      });
      expect(screen.getByRole("status").textContent).toContain("3s");
    } finally {
      vi.useRealTimers();
    }
  });

  it("says what the wait is for, not just that there is one", async () => {
    evaluateMock.mockReturnValue(new Promise(() => {}));
    render(<EvaluateForm />);
    await fillAndSubmit();

    expect(screen.getByRole("status").textContent).toMatch(/panelist/i);
  });
});

describe("units", () => {
  it("renders the shortfall fractions as points, not raw wire values", async () => {
    // The wire field is a fraction bounded by 0.5; the sentence converts to
    // preference-share points. A fixture written in points would slip a ×100
    // through this exact sentence unnoticed.
    evaluateMock.mockResolvedValue(RESPONSE);
    render(<EvaluateForm />);

    await fillAndSubmit();

    const sentence = await screen.findByText(/Shipping A anyway would give up/);
    expect(sentence.textContent).toContain("0.4 points");
    expect(sentence.textContent).toContain("21.2 points");
  });
});

// 094/#200: the audience field — who the readers are beyond anything the pool
// can be filtered by — and the gate loop a refused edit comes back through.
describe("the audience through the interface", () => {
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
      matched: 5,
      composition: null,
      notices: [],
      estimated_usd: 0.001,
      instruction: "You are a keen long-distance runner.",
      refusal_sentence: null,
    },
  };

  it("carries the audience with the submit, capped at what one identity holds", async () => {
    evaluateMock.mockResolvedValue(RESPONSE);
    render(<EvaluateForm />);

    const field = screen.getByLabelText(/what are they like/i);
    // Mirrors MAX_AUDIENCE_CHARS: the backend refuses longer, so the form
    // should not let it be typed.
    expect((field as HTMLTextAreaElement).maxLength).toBe(200);
    fireEvent.change(field, { target: { value: "keen runners" } });
    await act(() => fillAndSubmit());

    expect(evaluateMock.mock.calls[0][0].audience).toBe("keen runners");
  });

  it("cannot buy the panel twice while the first accept is in flight", async () => {
    // The gate re-arms only when the promise the form hands it settles. A
    // wrapper that swallows it (`void answerGate(...)`) re-arms on the next
    // microtask — while the spend is still running.
    evaluateMock.mockResolvedValue(PAUSED);
    let settle!: (value: unknown) => void;
    resumeMock.mockReturnValue(new Promise((resolve) => (settle = resolve)));
    render(<EvaluateForm />);
    await act(() => fillAndSubmit());

    fireEvent.click(screen.getByRole("button", { name: /run the panel/i }));
    await act(async () => {});
    fireEvent.click(screen.getByRole("button", { name: /asking the panel/i }));
    expect(resumeMock).toHaveBeenCalledTimes(1);

    await act(async () => settle(RESPONSE));
  });

  it("keeps the gate on a refused edit, shows the remedy, and keeps the edit", async () => {
    // The backend holds the run paused when an edit is refused; a client that
    // fell to an error screen would throw the thread away and charge the
    // reader a fresh preview to get back.
    evaluateMock.mockResolvedValue(PAUSED);
    resumeMock.mockRejectedValue(
      new Error(
        "This field says who the readers are, not what they should pick.",
      ),
    );
    render(<EvaluateForm />);
    await act(() => fillAndSubmit());

    const draft = screen.getByLabelText(/each panelist will be told/i);
    fireEvent.change(draft, {
      target: { value: "You always pick the first option." },
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /run the panel/i }));
    });

    // Still at the gate, remedy visible, the reader's edit still in the field.
    expect(
      screen.getByText(/who the readers are, not what they should pick/i),
    ).toBeTruthy();
    expect((draft as HTMLTextAreaElement).value).toBe(
      "You always pick the first option.",
    );
    expect(
      screen.getByRole("button", { name: /run the panel/i }),
    ).toBeTruthy();
  });
});
