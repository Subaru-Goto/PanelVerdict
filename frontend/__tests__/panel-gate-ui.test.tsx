import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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
  estimated_usd: 0.001,
};

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const preview = PREVIEW as any;

describe("the panel gate", () => {
  it("says how many people would be seated and what it would cost", async () => {
    render(<PanelGate preview={preview} onAccept={vi.fn()} onBack={vi.fn()} />);

    expect(screen.getByText(/5 people/i)).toBeTruthy();
    expect(screen.getByText(/\$0\.00/)).toBeTruthy();
  });

  it("only spends when a person says so", async () => {
    const onAccept = vi.fn();
    render(<PanelGate preview={preview} onAccept={onAccept} onBack={vi.fn()} />);

    expect(onAccept).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /run the panel/i }));

    expect(onAccept).toHaveBeenCalledTimes(1);
  });

  it("cannot be accepted twice", async () => {
    // Two clicks can land before React swaps this view out, and each one would
    // buy the panel.
    const onAccept = vi.fn();
    render(<PanelGate preview={preview} onAccept={onAccept} onBack={vi.fn()} />);

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

    fireEvent.click(screen.getByRole("button", { name: /change/i }));

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
