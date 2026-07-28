import type { ReactNode } from "react";

import type { PanelVerdict, VoteTally } from "../lib/api";
import { posteriorDensity } from "../lib/beta";
import { formatPercent } from "../lib/format";

/** 1% grid — finer than the curve's own width at any panel size we run. */
const SAMPLES = 101;

// SVG user units — the viewBox scales to the container, so only the ratios
// matter, not the absolute values.
const WIDTH = 600;
const BASELINE = 160;
const PLOT_TOP = 8;
const CRI_Y = 172;
/** Clears the CrI bar's 6px round caps below CRI_Y. */
const HEIGHT = 184;
/** Keeps 2px strokes at p = 0 and p = 1 inside the viewBox. */
const PAD = 4;

const x = (p: number): number => PAD + p * (WIDTH - 2 * PAD);
const y = (density: number): number =>
  BASELINE - density * (BASELINE - PLOT_TOP);

function LegendEntry({
  swatch,
  children,
}: {
  swatch: ReactNode;
  children: ReactNode;
}) {
  return (
    <li className="flex items-center gap-2">
      <svg viewBox="0 0 20 8" className="h-2 w-5 shrink-0" aria-hidden>
        {swatch}
      </svg>
      <span>{children}</span>
    </li>
  );
}

/** Caption saying what the curve is, axis ends carrying the actual headline
 *  text, and a legend naming every visible mark with its number — a mark with
 *  no on-screen name is deleted. */
export default function PosteriorChart({
  verdict,
  tally,
  variants,
}: {
  verdict: PanelVerdict;
  tally: VoteTally;
  variants: Record<string, string>;
}) {
  const points = posteriorDensity(
    tally.counts.a ?? 0,
    tally.counts.b ?? 0,
    SAMPLES,
  );
  const curve = points
    .map((point, i) => `${i === 0 ? "M" : "L"}${x(point.p)},${y(point.density)}`)
    .join(" ");
  // Fill and stroke are separate paths: a stroked closed area would draw its
  // own baseline as if it were data.
  const area = `${curve} L${x(1)},${BASELINE} L${x(0)},${BASELINE} Z`;
  const [criLow, criHigh] = verdict.credible_interval;
  const [ropeLow, ropeHigh] = verdict.rope;

  return (
    <figure className="flex flex-col gap-2 rounded border border-zinc-200 p-4 dark:border-zinc-800">
      <figcaption className="text-sm text-zinc-600 dark:text-zinc-400">
        How likely each possible split of the whole audience is, given these{" "}
        {tally.total} votes (
        {Object.entries(tally.counts)
          .map(([id, n]) => `${id.toUpperCase()} ${n}`)
          .join(" · ")}
        ).
      </figcaption>
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="h-auto w-full"
        role="img"
        aria-label="Posterior distribution of the share preferring B"
      >
        <rect
          x={x(ropeLow)}
          y={PLOT_TOP}
          width={x(ropeHigh) - x(ropeLow)}
          height={BASELINE - PLOT_TOP}
          className="fill-zinc-200/60 dark:fill-zinc-800/60"
        />
        <path d={area} className="fill-blue-600/10 dark:fill-blue-500/15" />
        <path
          d={curve}
          strokeWidth={2}
          strokeLinejoin="round"
          className="fill-none stroke-blue-600 dark:stroke-blue-500"
        />
        <line
          x1={x(verdict.share_preferring_b)}
          y1={PLOT_TOP}
          x2={x(verdict.share_preferring_b)}
          y2={BASELINE}
          strokeWidth={2}
          strokeDasharray="5 4"
          className="stroke-blue-600 dark:stroke-blue-500"
        />
        <line
          x1={x(0)}
          y1={BASELINE}
          x2={x(1)}
          y2={BASELINE}
          strokeWidth={1}
          className="stroke-zinc-300 dark:stroke-zinc-700"
        />
        <line
          x1={x(criLow)}
          y1={CRI_Y}
          x2={x(criHigh)}
          y2={CRI_Y}
          strokeWidth={6}
          strokeLinecap="round"
          className="stroke-blue-600 dark:stroke-blue-500"
        />
      </svg>
      <div className="flex justify-between gap-4 text-xs text-zinc-500">
        <span>← everyone prefers A: “{variants.a}”</span>
        <span className="text-right">everyone prefers B: “{variants.b}” →</span>
      </div>
      <ul className="flex flex-col gap-1 text-xs text-zinc-600 dark:text-zinc-400">
        <LegendEntry
          swatch={
            <line
              x1={0}
              y1={4}
              x2={20}
              y2={4}
              strokeWidth={2}
              strokeDasharray="4 3"
              className="stroke-blue-600 dark:stroke-blue-500"
            />
          }
        >
          Dashed line — panel mean: {formatPercent(verdict.share_preferring_b)}{" "}
          prefer B.
        </LegendEntry>
        <LegendEntry
          swatch={
            <line
              x1={2}
              y1={4}
              x2={18}
              y2={4}
              strokeWidth={6}
              strokeLinecap="round"
              className="stroke-blue-600 dark:stroke-blue-500"
            />
          }
        >
          Thick bar — the true share sits between {formatPercent(criLow)} and{" "}
          {formatPercent(criHigh)} ({formatPercent(verdict.credible_mass)}{" "}
          sure).
        </LegendEntry>
        <LegendEntry
          swatch={
            <rect
              x={0}
              y={0}
              width={20}
              height={8}
              className="fill-zinc-200 dark:fill-zinc-800"
            />
          }
        >
          Gray band — the tie zone: splits from {formatPercent(ropeLow)} to{" "}
          {formatPercent(ropeHigh)} read as even.
        </LegendEntry>
      </ul>
    </figure>
  );
}
