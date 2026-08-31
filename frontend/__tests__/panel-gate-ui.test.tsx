import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import PanelGate from "../app/components/panel-gate";

// The screen a reader sees before any money moves. 093/#198 owns how it looks;
// what is pinned here is what it must always say and never do.

afterEach(cleanup);

const PREVIEW = {
  query: {
    countries: ["JP"] as const,
    coverage: "requested" as const,
    min_age: 25,
    max_age: 40,
    gender: null,
    income_quintiles: [],
    education: [],
    traits: [],
    notices: [],
  },
  matched: 5,
  composition: {
    age_min: 25,
    age_median: 31,
    age_max: 40,
    countries: { JP: 5 },
    genders: { male: 3, female: 2 },
    education_levels: { tertiary: 5 },
    income_bands: { middle: 5 },
  },
  notices: [],
  // The wire always carries these: "" is a demographics-only run.
  instruction: "",
  refusal_sentence: null,
  estimated_usd: 0.001,
};

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const preview = PREVIEW as any;

describe("the panel gate", () => {
  it("shows panel size and matched count as plain numbers, with no price", async () => {
    render(
      <PanelGate
        preview={{ ...preview, matched: 312 }}
        onAccept={vi.fn()}
        onBack={vi.fn()}
      />,
    );

    // Seated (5, from the composition) and matched (312) are separate facts.
    expect(screen.getByText("5")).toBeTruthy();
    expect(screen.getByText("312")).toBeTruthy();
    expect(
      screen.getByText(/readers, each voting once and giving a reason/i),
    ).toBeTruthy();
    expect(
      screen.getByText(/personas in the pool that fit the description/i),
    ).toBeTruthy();
    // Cost is the footnote about the one small call — never a price tag.
    expect(screen.queryByText(/\$/)).toBeNull();
  });

  it("only spends when a person says so", async () => {
    const onAccept = vi.fn();
    render(
      <PanelGate preview={preview} onAccept={onAccept} onBack={vi.fn()} />,
    );

    expect(onAccept).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /run the panel/i }));

    expect(onAccept).toHaveBeenCalledTimes(1);
  });

  it("cannot be accepted twice", async () => {
    // Two clicks can land before React swaps this view out, and each one would
    // buy the panel.
    const onAccept = vi.fn();
    render(
      <PanelGate preview={preview} onAccept={onAccept} onBack={vi.fn()} />,
    );

    const run = screen.getByRole("button", { name: /run the panel/i });
    fireEvent.click(run);
    fireEvent.click(run);

    expect(onAccept).toHaveBeenCalledTimes(1);
    expect(
      screen.getByRole("button", { name: /asking the panel/i }),
    ).toHaveProperty("disabled", true);
  });

  it("offers a way back that spends nothing", async () => {
    const onBack = vi.fn();
    const onAccept = vi.fn();
    render(<PanelGate preview={preview} onAccept={onAccept} onBack={onBack} />);

    fireEvent.click(
      screen.getByRole("button", { name: /adjust the audience/i }),
    );

    expect(onBack).toHaveBeenCalled();
    expect(onAccept).not.toHaveBeenCalled();
  });

  it("shows a warning when nobody matches, and will not run", async () => {
    render(
      <PanelGate
        preview={{ ...preview, matched: 0, composition: null }}

        onAccept={vi.fn()}
        onBack={vi.fn()}
      />,
    );

    expect(screen.getByText(/nobody/i)).toBeTruthy();
    expect(
      screen.getByRole("button", { name: /run the panel/i }),
    ).toHaveProperty("disabled", true);
  });
});

// 094/#200: the sentence each panelist will act to be, shown at the gate
// where a human can change it. What is approved is exactly what runs.
describe("the selected reading at the gate", () => {
  it("shows the controls as fact rows, exactly as set", () => {
    // The reading is the caller's own controls (094) — no model read them, so
    // the gate can state them as facts rather than as an interpretation.
    const narrowed = {
      ...PREVIEW,
      query: {
        ...PREVIEW.query,
        countries: ["JP", "DE"],
        min_age: 30,
        max_age: 50,
        gender: "female",
        income_quintiles: [4, 5],
        education: ["tertiary"],
      },
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any;
    render(
      <PanelGate preview={narrowed} onAccept={vi.fn()} onBack={vi.fn()} />,
    );

    expect(screen.getByText(/Japan, Germany/)).toBeTruthy();
    expect(screen.getByText(/30–50/)).toBeTruthy();
    // getAllBy: the composition rows also say female — the fact row is one more
    expect(screen.getAllByText(/female/).length).toBeGreaterThan(1);
    expect(screen.getByText(/Q4, Q5/)).toBeTruthy();
    expect(screen.getAllByText(/tertiary/).length).toBeGreaterThan(1);
  });

  it("says everyone when no control narrowed anything", () => {
    // Untouched controls arrive expanded — every country, the full age span —
    // so "nothing narrowed" is a shape, not an absence.
    const everyone = {
      ...PREVIEW,
      query: {
        ...PREVIEW.query,
        countries: ["US", "JP", "DE"],
        min_age: 18,
        max_age: 100,
      },
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any;
    render(
      <PanelGate preview={everyone} onAccept={vi.fn()} onBack={vi.fn()} />,
    );

    expect(screen.getByText(/everyone in the pool/i)).toBeTruthy();
  });
});

describe("the instruction at the gate", () => {
  const withInstruction = {
    ...PREVIEW,
    instruction: "You are a keen long-distance runner.",
    refusal_sentence: null,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } as any;

  it("shows the sentence in an editable field", () => {
    render(
      <PanelGate
        preview={withInstruction}
        onAccept={vi.fn()}
        onBack={vi.fn()}
      />,
    );

    const field = screen.getByLabelText(
      /each panelist will act/i,
    ) as HTMLTextAreaElement;
    expect(field.value).toBe("You are a keen long-distance runner.");
  });

  it("accepts an untouched draft as absence — no check to pay for", () => {
    const onAccept = vi.fn();
    render(
      <PanelGate
        preview={withInstruction}
        onAccept={onAccept}
        onBack={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /run the panel/i }));

    expect(onAccept).toHaveBeenCalledWith(undefined);
  });

  it("accepts an edit as the edited sentence, exactly", () => {
    const onAccept = vi.fn();
    render(
      <PanelGate
        preview={withInstruction}
        onAccept={onAccept}
        onBack={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText(/each panelist will act/i), {
      target: { value: "You are a parent of young children." },
    });
    fireEvent.click(screen.getByRole("button", { name: /run the panel/i }));

    expect(onAccept).toHaveBeenCalledWith(
      "You are a parent of young children.",
    );
  });

  it("accepts a cleared field as an empty string — demographics only", () => {
    const onAccept = vi.fn();
    render(
      <PanelGate
        preview={withInstruction}
        onAccept={onAccept}
        onBack={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText(/each panelist will act/i), {
      target: { value: "" },
    });
    fireEvent.click(screen.getByRole("button", { name: /run the panel/i }));

    expect(onAccept).toHaveBeenCalledWith("");
  });

  it("says the sentence is role-played, not sampled", () => {
    // The honesty the field owes (094): panelists act this — no data picked
    // them by it. Without the framing, the sentence reads like a filter.
    render(
      <PanelGate
        preview={withInstruction}
        onAccept={vi.fn()}
        onBack={vi.fn()}
      />,
    );

    expect(screen.getByText(/not sampled/i)).toBeTruthy();
  });

  it("restores the model's draft after an edit, costing nothing", () => {
    // A caller out of checks can still run honestly: back to the draft whose
    // verdict was reached when it was written, which rides as absence.
    const onAccept = vi.fn();
    render(
      <PanelGate
        preview={withInstruction}
        onAccept={onAccept}
        onBack={vi.fn()}
      />,
    );

    const field = screen.getByLabelText(/each panelist will act/i);
    fireEvent.change(field, { target: { value: "You are someone else." } });
    fireEvent.click(
      screen.getByRole("button", { name: /restore the model.s draft/i }),
    );

    expect((field as HTMLTextAreaElement).value).toBe(
      "You are a keen long-distance runner.",
    );
    fireEvent.click(screen.getByRole("button", { name: /run the panel/i }));
    expect(onAccept).toHaveBeenCalledWith(undefined);
  });

  it("offers no restore while the draft is untouched", () => {
    render(
      <PanelGate
        preview={withInstruction}
        onAccept={vi.fn()}
        onBack={vi.fn()}
      />,
    );

    expect(
      screen.queryByRole("button", { name: /restore the model.s draft/i }),
    ).toBeNull();
  });

  it("shows no instruction field on a demographics-only run", () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const bare = { ...PREVIEW, instruction: "", refusal_sentence: null } as any;
    render(<PanelGate preview={bare} onAccept={vi.fn()} onBack={vi.fn()} />);

    expect(screen.queryByLabelText(/each panelist will act/i)).toBeNull();
  });

  it("says why an edit was refused, in our sentence, never the edit", () => {
    const onAccept = vi.fn();
    render(
      <PanelGate
        preview={withInstruction}
        notice="This field says who the readers are, not what they should pick."
        onAccept={onAccept}
        onBack={vi.fn()}
      />,
    );

    expect(
      screen.getByText(/who the readers are, not what they should pick/i),
    ).toBeTruthy();
    // A refusal re-opens the decision: the button must be pressable again.
    fireEvent.click(screen.getByRole("button", { name: /run the panel/i }));
    expect(onAccept).toHaveBeenCalledTimes(1);
  });
});

describe("the gate while an accept is in flight", () => {
  const withInstruction = {
    ...PREVIEW,
    instruction: "You are a keen long-distance runner.",
    refusal_sentence: null,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } as any;

  it("stays disabled for as long as the accept is in flight", async () => {
    // The synchronous double-click is caught by `sent`; this pins the slower
    // double-spend: a click, a beat while the request runs, another click.
    // The button may only re-arm when the promise the parent returns settles
    // — so the parent must return it, not swallow it with `void`.
    let settle!: () => void;
    const onAccept = vi.fn(
      () => new Promise<void>((resolve) => (settle = resolve)),
    );
    render(
      <PanelGate
        preview={withInstruction}
        onAccept={onAccept}
        onBack={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /run the panel/i }));
    // Let microtasks run: a swallowed promise re-arms here, a returned one not.
    await act(async () => {});
    fireEvent.click(screen.getByRole("button", { name: /asking the panel/i }));
    expect(onAccept).toHaveBeenCalledTimes(1);

    await act(async () => settle());
  });
});

// 077's settled presentation: the numbers are facts, the tags say how each
// row narrows the pool, and the one decision on the page sits in its own box.
describe("the settled gate presentation", () => {
  const withInstruction = {
    ...PREVIEW,
    instruction: "You are a young father.",
    refusal_sentence: null,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } as any;

  it("tags each control row Selected, and the audience words Role-played", () => {
    render(
      <PanelGate
        preview={withInstruction}
        audience="young dads."
        onAccept={vi.fn()}
        onBack={vi.fn()}
      />,
    );

    // One tag per control row: this query narrows country and age.
    expect(screen.getAllByText("Selected")).toHaveLength(2);
    // The words verbatim, quoted, trailing stop dropped — with the reason
    // they cannot be a filter.
    expect(screen.getByText(/\u201cyoung dads\u201d/)).toBeTruthy();
    expect(screen.getByText("Role-played")).toBeTruthy();
    expect(
      screen.getByText(/no data to pick them by — acted instead/i),
    ).toBeTruthy();
  });

  it("shows no role-played row when no words were given", () => {
    render(<PanelGate preview={preview} onAccept={vi.fn()} onBack={vi.fn()} />);

    expect(screen.queryByText("Role-played")).toBeNull();
  });

  it("draws who is seated as stacked strips with direct labels", () => {
    const seated = {
      ...preview,
      composition: {
        ...PREVIEW.composition,
        genders: { male: 3, female: 2 },
        education_levels: { below_secondary: 1, tertiary: 4 },
      },
    };
    render(<PanelGate preview={seated} onAccept={vi.fn()} onBack={vi.fn()} />);

    expect(screen.getByText("male · 60%")).toBeTruthy();
    expect(screen.getByText("female · 40%")).toBeTruthy();
    // The report's vocabulary, humanised the same way its rows are.
    expect(screen.getByText("below secondary · 20%")).toBeTruthy();
    expect(screen.getByText("tertiary · 80%")).toBeTruthy();
  });

  it("orders ordered dimensions by class, never by count", () => {
    const seated = {
      ...preview,
      composition: {
        ...PREVIEW.composition,
        income_bands: { upper: 4, lower: 1 },
      },
    };
    render(<PanelGate preview={seated} onAccept={vi.fn()} onBack={vi.fn()} />);

    const lower = screen.getByText("lower · 20%");
    const upper = screen.getByText("upper · 80%");
    expect(
      lower.compareDocumentPosition(upper) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("shows no role-played row when the words resolved entirely to controls", () => {
    // The translator can map words wholly onto demographics; the preview then
    // carries no instruction, and a row promising "the instruction below"
    // would point at nothing.
    render(
      <PanelGate
        preview={preview}
        audience="young dads."
        onAccept={vi.fn()}
        onBack={vi.fn()}
      />,
    );

    expect(screen.queryByText("Role-played")).toBeNull();
  });

  it("labels every segment for hover too — a sliver keeps its words", () => {
    const seated = {
      ...preview,
      composition: {
        ...PREVIEW.composition,
        genders: { male: 3, female: 2 },
      },
    };
    render(<PanelGate preview={seated} onAccept={vi.fn()} onBack={vi.fn()} />);

    expect(screen.getByText("male · 60%").getAttribute("title")).toBe(
      "male · 60%",
    );
  });

  it("says an edited sentence is checked, only once there is an edit", () => {
    render(
      <PanelGate
        preview={withInstruction}
        onAccept={vi.fn()}
        onBack={vi.fn()}
      />,
    );

    expect(screen.queryByText(/checked before it runs/i)).toBeNull();
    fireEvent.change(screen.getByLabelText(/each panelist will act/i), {
      target: { value: "You are a devoted father." },
    });
    expect(screen.getByText(/checked before it runs/i)).toBeTruthy();
  });

  it("boxes the one decision, cost reduced to the footnote", () => {
    render(<PanelGate preview={preview} onAccept={vi.fn()} onBack={vi.fn()} />);

    expect(
      screen.getByRole("heading", { name: /approve this reading\?/i }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: /looks right — run the panel/i }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: /adjust the audience/i }),
    ).toBeTruthy();
    expect(screen.getByText(/one small call/i)).toBeTruthy();
  });
});
