import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import EvaluateForm from "../app/components/evaluate-form";
import { makeResponse } from "./fixtures";

const { evaluateMock } = vi.hoisted(() => ({ evaluateMock: vi.fn() }));

vi.mock("../app/lib/api", () => ({ evaluate: evaluateMock }));

const RESPONSE = makeResponse();

afterEach(() => {
  cleanup();
  evaluateMock.mockReset();
});

function fillAndSubmit() {
  fireEvent.change(screen.getByLabelText(/who should judge/i), {
    target: { value: "Japanese homeowners" },
  });
  fireEvent.change(screen.getByLabelText(/headline a/i), {
    target: { value: "Save 50% today" },
  });
  fireEvent.change(screen.getByLabelText(/headline b/i), {
    target: { value: "Members save half" },
  });
  fireEvent.click(screen.getByRole("button", { name: /evaluate/i }));
}

describe("EvaluateForm", () => {
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
    expect(evaluateMock).toHaveBeenCalledWith({
      targetDescription: "",
      headlineA: "Save 50% today",
      headlineB: "Members save half",
    });
  });

  it("sends all three fields to evaluate", async () => {
    evaluateMock.mockResolvedValue(RESPONSE);
    render(<EvaluateForm />);

    fillAndSubmit();

    expect(evaluateMock).toHaveBeenCalledWith({
      targetDescription: "Japanese homeowners",
      headlineA: "Save 50% today",
      headlineB: "Members save half",
    });
  });

  it("renders notices with warnings distinguishable from readings", async () => {
    evaluateMock.mockResolvedValue(RESPONSE);
    render(<EvaluateForm />);

    fillAndSubmit();

    const warning = await screen.findByText(/did not vote/);
    const reading = screen.getByText(/Stopped after 50/);
    expect(warning.className).toContain("border-red");
    expect(reading.className).not.toContain("border-red");
  });

  it("renders the counts and says an early stop is an answer", async () => {
    evaluateMock.mockResolvedValue(RESPONSE);
    render(<EvaluateForm />);

    fillAndSubmit();

    expect(
      await screen.findByText(/50 of 200 matched panelists voted/),
    ).toBeTruthy();
    expect(screen.getByText(/stopped early: the call was already clear/))
      .toBeTruthy();
  });

  it("renders model output as literal text, never as markup", async () => {
    // The exfiltration defense from the 011 ticket: a reason carrying HTML must
    // reach the reader as characters. If this ever renders a <b> element, model
    // output has found a markup sink.
    evaluateMock.mockResolvedValue(RESPONSE);
    const { container } = render(<EvaluateForm />);

    fillAndSubmit();

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

    fillAndSubmit();

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

    fillAndSubmit();

    expect(await screen.findByText(/stand-in region was used/)).toBeTruthy();
  });

  it("says plainly when the panel carries no geographic targeting", async () => {
    // The 007 amendment: unmatched coverage resolves to the whole pool,
    // byte-identical to a deliberate global panel — only this flag can tell
    // the customer the difference, so it must sit with the verdict.
    evaluateMock.mockResolvedValue({
      ...RESPONSE,
      query: { ...RESPONSE.query, coverage: "unmatched" as const },
    });
    render(<EvaluateForm />);

    fillAndSubmit();

    const flag = await screen.findByText(/no geographic targeting/);
    expect(flag.className).toContain("text-red");
  });
});

describe("request lifecycle", () => {
  it("keeps submit disabled while a run is in flight", () => {
    evaluateMock.mockReturnValue(new Promise(() => {}));
    render(<EvaluateForm />);

    fillAndSubmit();

    const button = screen.getByRole("button", { name: /asking the panel/i });
    expect(button.hasAttribute("disabled")).toBe(true);
  });

  it("shows the backend's refusal sentence when the run fails", async () => {
    evaluateMock.mockRejectedValue(
      new Error("OpenRouter credit is exhausted and no vote was cast."),
    );
    render(<EvaluateForm />);

    fillAndSubmit();

    expect(
      await screen.findByText(/Error: OpenRouter credit is exhausted/),
    ).toBeTruthy();
  });
});

describe("units", () => {
  it("renders the shortfall fractions as points, not raw wire values", async () => {
    // The wire field is a fraction bounded by 0.5; the sentence converts to
    // preference-share points. A fixture written in points would slip a ×100
    // through this exact sentence unnoticed.
    evaluateMock.mockResolvedValue(RESPONSE);
    render(<EvaluateForm />);

    fillAndSubmit();

    const sentence = await screen.findByText(/Shipping A anyway would give up/);
    expect(sentence.textContent).toContain("0.4 points");
    expect(sentence.textContent).toContain("21.2 points");
  });
});
