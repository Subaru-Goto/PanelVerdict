"use client";

import type { ReactNode } from "react";

import type {
  EducationLevel,
  EvaluateResponse,
  Notice,
  PanelVerdict,
  TraitLevel,
  TraitName,
  TraitRequest,
  Vote,
  VoterSummary,
} from "../lib/api";
import { formatPercent, formatPoints } from "../lib/format";
import AnalystDock from "./analyst-dock";
import { useAnalyst, OPENING_REQUEST, type Analyst } from "../lib/use-analyst";
import PosteriorChart from "./posterior-chart";

/** Max, not B's: either direction can be the one worth acting on and the payload does not
 *  say which leads. */
const strongestPreference = (verdict: PanelVerdict): number =>
  Math.max(
    verdict.probability_meaningfully_preferred.a,
    verdict.probability_meaningfully_preferred.b,
  );

type Recommendation = "lean" | "tie" | "no_call";

/** Derived here rather than delivered as a label, so the probability it rests on stays on
 *  screen beside it. The bar is the verdict's own `credible_mass` — the credibility
 *  everything else in the report is already stated at, so no second number is introduced
 *  that a reader would have to be told about separately. */
const recommend = (verdict: PanelVerdict): Recommendation => {
  if (strongestPreference(verdict) >= verdict.credible_mass) return "lean";
  if (verdict.probability_practical_tie >= verdict.credible_mass) return "tie";
  return "no_call";
};

const VERDICT_COPY: Record<
  Recommendation,
  { headline: string; advice: string }
> = {
  lean: {
    headline: "Panel leans clearly",
    advice: "The lead is wide enough to be worth acting on.",
  },
  tie: {
    headline: "Practical tie",
    advice:
      "Credibly too close to matter — pick either, or test a bolder variant.",
  },
  no_call: {
    headline: "No call at this credibility",
    advice:
      "Read the probabilities below and decide against your own bar; more votes would sharpen them.",
  },
};

/** Which variant the panel leans toward. B is only the reference, not the default. */
const leadingSide = (verdict: PanelVerdict): "a" | "b" =>
  verdict.share_preferring_b >= 0.5 ? "b" : "a";

const leadingShare = (verdict: PanelVerdict): number =>
  Math.max(verdict.share_preferring_b, 1 - verdict.share_preferring_b);

function Chip({
  tone = "neutral",
  children,
}: {
  tone?: "neutral" | "alert";
  children: ReactNode;
}) {
  return (
    <span
      className={
        tone === "alert"
          ? "rounded-full border border-red-400 px-2 py-0.5 text-xs text-red-600 dark:border-red-700 dark:text-red-400"
          : "rounded-full border border-zinc-300 px-2 py-0.5 text-xs dark:border-zinc-700"
      }
    >
      {children}
    </span>
  );
}

function StatTile({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail?: string;
}) {
  return (
    <div className="flex flex-col gap-1 rounded border border-zinc-200 p-3 dark:border-zinc-800">
      <p className="text-xs text-zinc-500">{label}</p>
      <p className="text-lg font-semibold">{value}</p>
      {detail !== undefined && (
        <p className="text-xs text-zinc-500">{detail}</p>
      )}
    </div>
  );
}

function NoticeList({ notices }: { notices: Notice[] }) {
  if (notices.length === 0) return null;
  return (
    <ul className="flex flex-col gap-1">
      {notices.map((notice, index) => (
        <li
          key={index}
          className={
            notice.severity === "warning"
              ? "rounded border-l-4 border-dotted border-red-400 bg-red-50 p-2 text-sm dark:border-red-700 dark:bg-red-950"
              : "rounded border-l-4 border-zinc-300 bg-zinc-50 p-2 text-sm text-zinc-600 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-400"
          }
        >
          {notice.message}
        </li>
      ))}
    </ul>
  );
}

const formatLevel = (level: TraitLevel): string => level.replace("_", " ");

function TraitChip({ trait }: { trait: TraitRequest }) {
  return (
    <Chip>
      {trait.trait}: {formatLevel(trait.level)} — from “{trait.source_phrase}”
    </Chip>
  );
}

function PanelCard({ result }: { result: EvaluateResponse }) {
  const { query, counts, notices, stop_reason } = result;
  return (
    <div className="flex flex-col gap-3 rounded border border-zinc-200 p-4 dark:border-zinc-800">
      <div className="flex items-center gap-2">
        <h2 className="text-sm font-medium">Panel</h2>
        {query.coverage !== "requested" && (
          <Chip tone={query.coverage === "unmatched" ? "alert" : "neutral"}>
            coverage: {query.coverage}
          </Chip>
        )}
      </div>
      <div className="flex flex-wrap gap-1">
        {query.countries.map((country) => (
          <Chip key={country}>{country}</Chip>
        ))}
        {query.traits.map((trait) => (
          <TraitChip key={trait.trait} trait={trait} />
        ))}
      </div>
      {query.coverage === "approximated" && (
        <p className="text-sm text-zinc-500">
          A stand-in region was used — the notice below names it.
        </p>
      )}
      <NoticeList notices={notices} />
      <p className="text-sm text-zinc-500">
        {counts.voted} of {counts.matched} matched panelists voted (
        {counts.requested} requested)
        {stop_reason !== null &&
          " — stopped early: the call was already clear, and more votes would only have narrowed the range, not changed it"}
        .
      </p>
    </div>
  );
}

// Mirrors BigFive's field order — the one trait order the whole product speaks
// (backend schemas.py pins it). The Record check keeps this copy exhaustive:
// dropping or misspelling a trait fails the build.
const TRAIT_ORDER = Object.keys({
  openness: true,
  conscientiousness: true,
  extraversion: true,
  agreeableness: true,
  neuroticism: true,
} satisfies Record<TraitName, true>) as TraitName[];

// Compact forms of the education phrases the vote prompt renders (backend
// panel.py). "Below secondary" is someone who left before finishing — not
// someone who never attended.
const EDUCATION_LABEL: Record<EducationLevel, string> = {
  below_secondary: "didn’t finish secondary school",
  secondary: "secondary school",
  tertiary: "university degree",
};

const voterLine = (voter: VoterSummary): string =>
  `${voter.age} · ${voter.gender} · ${voter.country} · ` +
  `${EDUCATION_LABEL[voter.education]} · ${voter.income_band} income`;

function VoteList({ votes }: { votes: Vote[] }) {
  return (
    // Closed by default: the summary above is the reading, and every reason in
    // full is detail a click away rather than a scroll past. The synthetic
    // caveat deliberately lives on the summary card, not in here — a reader
    // who never opens this must still meet it.
    <details className="flex flex-col gap-2">
      <summary className="cursor-pointer text-sm font-medium">
        What the panelists said ({votes.length} in their own words)
      </summary>
      <ul className="mt-2 flex flex-col gap-2">
        {votes.map((vote) => (
          <li
            key={vote.persona_id}
            className="flex flex-col gap-1 rounded border border-zinc-200 p-3 text-sm dark:border-zinc-800"
          >
            <span className="font-medium">
              Chose {vote.chosen_variant_id.toUpperCase()}
            </span>
            <p className="text-zinc-600 dark:text-zinc-400">{vote.reason}</p>
            <p className="text-xs text-zinc-500">{voterLine(vote.voter)}</p>
            <details className="text-xs">
              <summary className="cursor-pointer text-zinc-500">
                personality
              </summary>
              <div className="mt-1 flex flex-wrap gap-1">
                {TRAIT_ORDER.map((trait) => (
                  <Chip key={trait}>
                    {trait}: {formatLevel(vote.voter.traits[trait])}
                  </Chip>
                ))}
              </div>
            </details>
          </li>
        ))}
      </ul>
    </details>
  );
}

/** The analyst's opening turn, rendered as the report's own reading of the
 *  panel. It is turn 1 of the dock's thread rather than a separate call, so a
 *  follow-up resolves against words already in the transcript. */
function SummaryCard({ analyst }: { analyst: Analyst }) {
  const reply = analyst.turns.find((turn) => turn.role === "analyst");
  return (
    <div className="flex flex-col gap-2 rounded border border-zinc-200 p-4 dark:border-zinc-800">
      <h2 className="text-sm font-medium">What the panel said</h2>
      {reply?.role === "analyst" && (
        <>
          {reply.text !== "" && (
            <p className="whitespace-pre-wrap text-sm">{reply.text}</p>
          )}
          {reply.status !== null && (
            <p className="text-sm italic text-zinc-500">{reply.status}</p>
          )}
          {reply.error !== null && (
            <p className="text-sm text-red-600 dark:text-red-400">
              {reply.error}
            </p>
          )}
        </>
      )}
      <p className="text-xs text-zinc-500">
        A reading of reasons written by synthetic panelists — sampled personas,
        not real people.
      </p>
    </div>
  );
}

export default function Report({ result }: { result: EvaluateResponse }) {
  const analyst = useAnalyst(result, OPENING_REQUEST);
  const { verdict, tally, variants } = result;
  const copy = VERDICT_COPY[recommend(verdict)];
  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs font-medium dark:bg-zinc-800">
          {copy.headline}
        </span>
        <span className="text-lg font-semibold">
          {leadingSide(verdict) === "b" ? variants.b : variants.a}
        </span>
        <span className="text-sm text-zinc-500">
          {formatPercent(leadingShare(verdict))} of the panel prefer it.
        </span>
      </div>
      {result.query.coverage === "unmatched" && (
        <p className="text-sm text-red-600 dark:text-red-400">
          The region you named could not be matched — this panel carries no
          geographic targeting.
        </p>
      )}
      <p className="text-sm text-zinc-500">{copy.advice}</p>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <StatTile
          label="Share preferring B"
          value={formatPercent(verdict.share_preferring_b)}
          detail={`true share is between ${formatPercent(verdict.credible_interval[0])} and ${formatPercent(verdict.credible_interval[1])} (${formatPercent(verdict.credible_mass)} sure)`}
        />
        <StatTile
          label="Chance A is preferred"
          value={formatPercent(verdict.probability_meaningfully_preferred.a)}
          detail="by more than the tie zone"
        />
        <StatTile
          label="Chance B is preferred"
          value={formatPercent(verdict.probability_meaningfully_preferred.b)}
          detail="by more than the tie zone"
        />
        <StatTile
          label="Practical tie"
          value={formatPercent(verdict.probability_practical_tie)}
          detail="chance the true split lands in the tie zone"
        />
      </div>
      <p className="text-sm text-zinc-500">
        The verdict above only calls a lean or a tie when its chance clears{" "}
        {formatPercent(verdict.credible_mass)}.{" "}
        {verdict.detectable_gap !== null && (
          <>
            This panel can only detect leans of{" "}
            {formatPoints(verdict.detectable_gap)} or more — a smaller true
            lean reads as no call, not as a tie.{" "}
          </>
        )}
        Shipping A anyway would give up{" "}
        {formatPoints(verdict.expected_preference_shortfall.shipping_a)} of
        preference on average; shipping B would give up{" "}
        {formatPoints(verdict.expected_preference_shortfall.shipping_b)}.
      </p>
      <PosteriorChart verdict={verdict} tally={tally} variants={variants} />
      <p className="text-xs text-zinc-500">
        The panel chose <em>between</em> both headlines. Real readers usually
        see only one, so this is a preference share, not a predicted
        click-through rate — and it is unvalidated where two variants say the
        same thing differently.
      </p>
      <PanelCard result={result} />
      <SummaryCard analyst={analyst} />
      <VoteList votes={result.votes} />
      <AnalystDock analyst={analyst} />
    </section>
  );
}
