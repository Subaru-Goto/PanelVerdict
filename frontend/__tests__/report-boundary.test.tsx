import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  AnalystBoundary,
  ReportBoundary,
} from "../app/components/report-boundary";

function Broken(): never {
  throw new TypeError("cannot read properties of undefined");
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("the report boundary (049/#147)", () => {
  it("replaces a crashed report with one sentence and a Refresh button", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const refresh = vi.fn();

    render(
      <ReportBoundary onRefresh={refresh}>
        <Broken />
      </ReportBoundary>,
    );

    expect(
      screen.getByText(
        "Something went wrong drawing this report. Refresh to load it again.",
      ),
    ).toBeTruthy();
    // The error's own words are for the console, never the reader.
    expect(screen.queryByText(/undefined/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("renders its children untouched when nothing throws", () => {
    render(
      <ReportBoundary onRefresh={() => {}}>
        <p>the verdict</p>
      </ReportBoundary>,
    );

    expect(screen.getByText("the verdict")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Refresh" })).toBeNull();
  });

  it("keeps the report on screen when only the analyst crashes", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});

    render(
      <ReportBoundary onRefresh={() => {}}>
        <p>the verdict</p>
        <AnalystBoundary onRefresh={() => {}}>
          <Broken />
        </AnalystBoundary>
      </ReportBoundary>,
    );

    expect(screen.getByText("the verdict")).toBeTruthy();
    expect(
      screen.getByText(
        "The analyst is unavailable right now. Refresh to try again.",
      ),
    ).toBeTruthy();
  });
});
