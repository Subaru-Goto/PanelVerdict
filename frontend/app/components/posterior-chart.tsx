import type { ReactNode } from "react";

import type { PanelVerdict, VoteTally } from "../lib/api";
import { posteriorDensity } from "../lib/beta";
import { formatPercent, formatSplit } from "../lib/format";
import { isPracticalTie, leadingSide } from "../lib/verdict";

/** 1% grid — finer than the curve's own width at any panel size we run. */
const SAMPLES = 101;

// SVG user units — the viewBox scales to the container, so only the ratios
// matter, not the absolute values.
const WIDTH = 600;
/** The mean label's text baseline, in the headroom band above the plot — the
 *  curve's peak reaches PLOT_TOP, so a label inside the plot collides with it. */
const LABEL_Y = 14;
const PLOT_TOP = 24;
const BASELINE = 176;
const CRI_Y = 188;
/** Clears the CrI bar's 6px round caps below CRI_Y, plus the fallback row an
 *  interval end drops to when it would otherwise run off the plot's edge. */
const HEIGHT = 214;
const CRI_FALLBACK_Y = CRI_Y + 18;
/** Roughly the width of "100%" at fontSize 11 — the room an edge label needs on
 *  its own side before it starts crossing the viewBox boundary. */
const EDGE_LABEL = 26;
/** Keeps 2px strokes at p = 0 and p = 1 inside the viewBox. */
const PAD = 4;

const x = (p: number): number => PAD + p * (WIDTH - 2 * PAD);
const y = (density: number): number =>
  BASELINE - density * (BASELINE - PLOT_TOP);

/** Plain words on top, the technical name under them in small type. The name
 *  is there so a reader who knows the term can check our arithmetic, and under
 *  the plain words so a reader who does not is never made to learn it first. */
function LegendEntry({
  swatch,
  plain,
  technical,
}: {
  swatch: ReactNode;
  plain: string;
  technical: string;
}) {
  return (
    <li className="flex items-start gap-2">
      <svg viewBox="0 0 20 8" className="mt-1.5 h-2 w-5 shrink-0" aria-hidden>
        {swatch}
      </svg>
      <span className="flex flex-col leading-snug">
        <span>{plain}</span>
        <span className="text-[0.6875rem] text-zinc-500 dark:text-zinc-400">
          ({technical})
        </span>
      </span>
    </li>
  );
}

/** Caption saying what the curve is, axis ends carrying the actual headline
 *  text, and a legend naming every visible mark — a mark with no on-screen name
 *  is deleted.
 *
 *  Every figure is drawn once, at the mark it measures. The legend used to
 *  restate the mean, both interval ends, both band edges and the credible mass,
 *  a few pixels from where the plot already drew them; a reader comparing the
 *  two was comparing a number with itself (093). */
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
    .map(
      (point, i) => `${i === 0 ? "M" : "L"}${x(point.p)},${y(point.density)}`,
    )
    .join(" ");
  // Fill and stroke are separate paths: a stroked closed area would draw its
  // own baseline as if it were data.
  const area = `${curve} L${x(1)},${BASELINE} L${x(0)},${BASELINE} Z`;
  const [criLow, criHigh] = verdict.credible_interval;
  const [ropeLow, ropeHigh] = verdict.rope;
  const mean = verdict.share_preferring_b;
  // The chart lives in B-space, so the leading side's share appears nowhere on
  // the plot without this — a reader at the dashed line had to compute 100 − 29
  // themselves. Fixed A-then-B order, matching the lead.
  // Rounded as a pair, not twice: an even panel printed "50% prefer A · 51%
  // prefer B", which is the tie state contradicting itself in its own caption.
  const [shareA, shareB] = formatSplit(mean);
  const meanLabel = `estimated split: ${shareA} prefer A · ${shareB} prefer B`;
  // Flipping the anchor keeps the label inside the viewBox wherever the mean sits.
  const labelOnRight = mean <= 0.5;

  // The lead says "N% likely people genuinely prefer this one". N is the mass of
  // this curve past the tie band, so it is drawable — and drawing it is the
  // point: the mean and the probability are two different numbers on one chart,
  // and reading the first as the answer is a mistake this prototype caught its
  // own author making. The area carries the figure it measures.
  const leading = leadingSide(verdict);
  // Which way the tail runs, decided once. Six marks depend on it, and six
  // copies of the same ternary is how one of them ends up pointing the wrong
  // way without any of the others noticing.
  const side =
    leading === "b"
      ? {
          bandEdge: ropeHigh,
          plotEdge: 1,
          inTail: (p: number) => p >= ropeHigh,
        }
      : {
          bandEdge: ropeLow,
          plotEdge: 0,
          inTail: (p: number) => p <= ropeLow,
        };

  // The grid spans a closed [0, 1] and the band lies inside it, so the tail
  // always holds at least the plot edge — there is no empty case to guard.
  const tail = points.filter((point) => side.inTail(point.p));
  // Walked from the band outward either way, so the polygon closes on the
  // baseline at the plot's edge rather than crossing itself.
  const walk = side.plotEdge === 1 ? tail : [...tail].reverse();
  const massArea =
    `M${x(side.bandEdge)},${BASELINE} ` +
    walk.map((point) => `L${x(point.p)},${y(point.density)}`).join(" ") +
    ` L${x(side.plotEdge)},${BASELINE} Z`;
  // When the tie is itself the finding, the annotation moves onto the band.
  // It used to annotate the tail in every state, so a tied panel wrote its
  // largest, boldest number over its smallest region — 3% on a sliver, while
  // the 95% the report was actually about sat in an unlabelled grey rectangle.
  // The gesture is unchanged: one figure, on the region the lead is about.
  const tie = isPracticalTie(verdict);
  const inBand = points.filter(
    (point) => point.p >= ropeLow && point.p <= ropeHigh,
  );
  // The tail always reaches the plot's edge, so it is never empty. The band
  // is: it arrives in the payload, and one narrow enough to fall between two
  // columns of the grid catches none of them — which would leave `target`
  // undefined and take the whole report down. The nearest column to its middle
  // is the honest stand-in.
  const middle = (ropeLow + ropeHigh) / 2;
  const annotated = !tie
    ? walk
    : inBand.length > 0
      ? inBand
      : [
          points.reduce((best, point) =>
            Math.abs(point.p - middle) < Math.abs(best.p - middle)
              ? point
              : best,
          ),
        ];
  // The tallest point of the annotated region, at half its height — the one
  // place guaranteed to have area under it whatever the curve does. The middle
  // of the tail's *width* is not: on a near-tie the shaded sliver sits against
  // the band and the width's middle is far out where the curve has gone flat,
  // so the line pointed at blank paper.
  const target = annotated.reduce(
    (best, point) => (point.density > best.density ? point : best),
    annotated[0],
  );
  // Opposite the mean, never on the leading side: the mass and the peak sit on
  // the same side of the band, so a label in the leader's own corner is written
  // straight across the tallest part of the curve. `labelOnRight` already picks
  // the empty half for the mean's own label, for the same reason. A tie needs
  // this more, not less — its annotated region sits directly under the peak.
  const annotationX = labelOnRight ? WIDTH - PAD - 6 : PAD + 6;
  const annotationAnchor = labelOnRight ? ("end" as const) : ("start" as const);
  const annotationShare = formatPercent(
    tie
      ? verdict.probability_practical_tie
      : verdict.probability_meaningfully_preferred[leading],
  );
  // The caption names the region the leader points at, in the legend's own
  // plain words for it. On a tie that has to be said rather than implied: the
  // reader's default reading of a big number on this chart is "how far ahead
  // the winner is", which is the opposite of what a tie means.
  const annotationCaption = tie ? "practically a tie" : "posterior probability";

  // An interval end sits beside its bar, outside it — until the bar reaches the
  // plot's edge and there is no "outside" left. A decisive panel printed "%"
  // with its digits cut off the viewBox, so a squeezed end now drops to its own
  // row underneath rather than being drawn where it cannot be read.
  const lowLabel =
    x(criLow) - 8 < EDGE_LABEL
      ? { x: PAD, y: CRI_FALLBACK_Y, anchor: "start" as const }
      : { x: x(criLow) - 8, y: CRI_Y + 4, anchor: "end" as const };
  const highLabel =
    x(criHigh) + 8 > WIDTH - EDGE_LABEL
      ? { x: WIDTH - PAD, y: CRI_FALLBACK_Y, anchor: "end" as const }
      : { x: x(criHigh) + 8, y: CRI_Y + 4, anchor: "start" as const };
  // Every mark inside an `img` is invisible to a screen reader, so the label
  // has to carry what the plot says — where the curve sits, and the figure the
  // annotation draws on it. Without this the chart announces its title alone.
  const chartLabel =
    `Posterior distribution of the share preferring B. ` +
    `The estimated split is ${shareA} preferring A and ` +
    `${shareB} preferring B, and B's true share sits between ` +
    `${formatPercent(criLow)} and ${formatPercent(criHigh)} at ` +
    `${formatPercent(verdict.credible_mass)} credibility. ` +
    (tie
      ? `${annotationShare} of the curve lies inside the tie zone: the difference ` +
        `is credibly too small to matter.`
      : `${annotationShare} of the curve lies past the tie zone, on ` +
        `${leading.toUpperCase()}'s side.`);

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
        aria-label={chartLabel}
      >
        <rect
          x={x(ropeLow)}
          y={PLOT_TOP}
          width={x(ropeHigh) - x(ropeLow)}
          height={BASELINE - PLOT_TOP}
          data-mark="rope"
          className="fill-zinc-200/60 dark:fill-zinc-800/60"
        />
        <path d={area} className="fill-blue-600/10 dark:fill-blue-500/15" />
        {/* `data-mark` on the band and the mass: an SVG shape carries no role,
            so this is the only handle a test has on which side got shaded. */}
        <path
          d={massArea}
          data-mark="mass"
          className="fill-blue-600/25 dark:fill-blue-500/30"
        />
        <path
          d={curve}
          data-mark="curve"
          strokeWidth={2}
          strokeLinejoin="round"
          className="fill-none stroke-blue-600 dark:stroke-blue-500"
        />
        <line
          x1={x(mean)}
          y1={PLOT_TOP}
          x2={x(mean)}
          y2={BASELINE}
          strokeWidth={2}
          strokeDasharray="5 4"
          className="stroke-blue-600 dark:stroke-blue-500"
        />
        <text
          x={labelOnRight ? x(mean) + 8 : x(mean) - 8}
          y={LABEL_Y}
          textAnchor={labelOnRight ? "start" : "end"}
          fontSize={12}
          className="fill-zinc-600 dark:fill-zinc-400"
        >
          {meanLabel}
        </text>
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
        <text
          data-mark="cri-low"
          x={lowLabel.x}
          y={lowLabel.y}
          textAnchor={lowLabel.anchor}
          fontSize={11}
          className="fill-zinc-500 dark:fill-zinc-400"
        >
          {formatPercent(criLow)}
        </text>
        <text
          data-mark="cri-high"
          x={highLabel.x}
          y={highLabel.y}
          textAnchor={highLabel.anchor}
          fontSize={11}
          className="fill-zinc-500 dark:fill-zinc-400"
        >
          {formatPercent(criHigh)}
        </text>
        <line
          data-mark="leader"
          x1={annotationX}
          y1={68}
          x2={x(target.p)}
          y2={(y(target.density) + BASELINE) / 2}
          strokeWidth={1}
          className="stroke-zinc-500 dark:stroke-zinc-400"
        />
        <text
          x={annotationX}
          y={48}
          textAnchor={annotationAnchor}
          fontSize={16}
          fontWeight={600}
          className="fill-zinc-800 dark:fill-zinc-100"
        >
          {annotationShare}
        </text>
        <text
          x={annotationX}
          y={62}
          textAnchor={annotationAnchor}
          fontSize={9}
          letterSpacing={0.8}
          className="fill-zinc-500 uppercase dark:fill-zinc-400"
        >
          {annotationCaption}
        </text>
      </svg>
      <div className="flex justify-between gap-4 text-xs text-zinc-500">
        <span>← prefer A — “{variants.a}”</span>
        <span className="text-right">prefer B — “{variants.b}” →</span>
      </div>
      <ul
        role="list"
        aria-label="What each mark on the chart means"
        className="flex flex-wrap gap-x-6 gap-y-2 text-xs text-zinc-600 dark:text-zinc-400"
      >
        <LegendEntry
          swatch={
            <>
              {/* Two rects, because on the plot the mass is painted over the
                  wash under the whole curve — one rect would name a blue that
                  appears nowhere. */}
              <rect
                x={0}
                y={0}
                width={20}
                height={8}
                className="fill-blue-600/10 dark:fill-blue-500/15"
              />
              <rect
                x={0}
                y={0}
                width={20}
                height={8}
                className="fill-blue-600/25 dark:fill-blue-500/30"
              />
            </>
          }
          plain="Genuinely preferred"
          technical="posterior probability"
        />
        <LegendEntry
          swatch={
            <line
              x1={0}
              y1={4}
              x2={20}
              y2={4}
              strokeWidth={2}
              strokeDasharray="5 4"
              className="stroke-blue-600 dark:stroke-blue-500"
            />
          }
          plain="Most likely"
          technical="mean"
        />
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
          plain="Plausible range"
          technical={`${formatPercent(verdict.credible_mass)} HDI`}
        />
        <LegendEntry
          swatch={
            <rect
              x={0}
              y={0}
              width={20}
              height={8}
              className="fill-zinc-200/60 dark:fill-zinc-800/60"
            />
          }
          plain="Practically a tie"
          technical="ROPE"
        />
      </ul>
    </figure>
  );
}
