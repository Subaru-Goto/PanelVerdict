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
  VoteTally,
} from "../lib/api";
import { formatPercent, formatPoints } from "../lib/format";
import AnalystDock from "./analyst-dock";
import { useAnalyst, OPENING_REQUEST, type Analyst } from "../lib/use-analyst";
import PosteriorChart from "./posterior-chart";
import { isPracticalTie, leadingSide } from "../lib/verdict";

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
          ? "rounded-full border border-red px-2 py-0.5 text-xs text-red"
          : "rounded-full border border-line px-2 py-0.5 text-xs"
      }
    >
      {children}
    </span>
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
              ? "rounded border-l-4 border-dotted border-red bg-red/5 p-2 text-sm"
              : "rounded border-l-4 border-line bg-surface-2 p-2 text-sm text-ink-2"
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
  const { query, counts, notices } = result;
  return (
    <div className="flex flex-col gap-3 rounded border border-line p-4">
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
        <p className="text-sm text-ink-2">
          A stand-in region was used — the notice below names it.
        </p>
      )}
      <NoticeList notices={notices} />
      <p className="text-sm text-ink-2">
        {counts.voted} of {counts.matched} matched panelists voted (
        {counts.requested} requested).
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
            className="flex flex-col gap-1 rounded border border-line p-3 text-sm"
          >
            <span className="font-medium">
              Chose {vote.chosen_variant_id.toUpperCase()}
            </span>
            <p className="text-ink-2">{vote.reason}</p>
            <p className="text-xs text-ink-2">{voterLine(vote.voter)}</p>
            <details className="text-xs">
              <summary className="cursor-pointer text-ink-2">
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
    <div className="flex flex-col gap-2 rounded border border-line p-4">
      <h2 className="text-sm font-medium">What the panel said</h2>
      {reply?.role === "analyst" && (
        <>
          {reply.text !== "" && (
            <p className="whitespace-pre-wrap text-sm">{reply.text}</p>
          )}
          {reply.status !== null && (
            <p className="text-sm italic text-ink-2">{reply.status}</p>
          )}
          {reply.error !== null && (
            <p className="text-sm text-red">{reply.error}</p>
          )}
        </>
      )}
      <p className="text-xs text-ink-2">
        A reading of reasons written by synthetic panelists — sampled personas,
        not real people.
      </p>
    </div>
  );
}

/** The report's answer, said in words (020, 093).
 *
 *  The percentage is the mass past the tie zone — the number the chart's curve
 *  carries, *not* the share of the panel, which is a different question and the
 *  swap `report.test.tsx` guards. The qualifier follows the claim rather than
 *  joining it, so what is claimed lands before what it excludes. */
function Lead({
  verdict,
  tally,
  variants,
}: {
  verdict: PanelVerdict;
  tally: VoteTally;
  variants: Record<string, string>;
}) {
  const leading = leadingSide(verdict);
  const trailing = leading === "a" ? "b" : "a";
  return (
    <div className="flex flex-col gap-2">
      <p className="text-2xl font-semibold">“{variants[leading]}”</p>
      <p className="text-sm text-ink-2">over “{variants[trailing]}”</p>
      <p className="text-lg">
        {formatPercent(verdict.probability_meaningfully_preferred[leading])}{" "}
        likely people genuinely prefer this one.
      </p>
      <p className="text-sm text-ink-2">
        Wins too small to matter don’t count towards that number.
      </p>
      <p className="text-sm text-ink-2">
        {tally.counts[leading] ?? 0} of {tally.total} panelists preferred it.
      </p>
      {isPracticalTie(verdict) && (
        <p className="text-sm">
          These two are equally good — the difference is too small to be worth
          choosing over.
        </p>
      )}
    </div>
  );
}

export default function Report({
  result,
  analyst: analystMode = "live",
}: {
  result: EvaluateResponse;
  /** "locked" on the demo (061): the analyst spends from a signed-in
   *  account's budget, so a sample offers a line saying why, not a dead
   *  control — and asks the backend nothing. */
  analyst?: "live" | "locked";
}) {
  // The hook always runs (rules of hooks); an undefined opening asks nothing.
  const analyst = useAnalyst(
    result,
    analystMode === "live" ? OPENING_REQUEST : undefined,
  );
  const { verdict, tally, variants } = result;
  return (
    <section className="flex flex-col gap-4">
      <Lead verdict={verdict} tally={tally} variants={variants} />
      {result.query.coverage === "unmatched" && (
        <p className="text-sm text-red">
          The region you named could not be matched — this panel carries no
          geographic targeting.
        </p>
      )}
      <p className="text-sm text-ink-2">
        {verdict.detectable_gap !== null && (
          <>
            This panel can only detect leans of{" "}
            {formatPoints(verdict.detectable_gap)} or more — a smaller true lean
            cannot be told apart from an even split.{" "}
          </>
        )}
        Shipping A would give up{" "}
        {formatPoints(verdict.expected_preference_shortfall.shipping_a)} of
        preference on average; shipping B would give up{" "}
        {formatPoints(verdict.expected_preference_shortfall.shipping_b)}.
      </p>
      <PosteriorChart verdict={verdict} tally={tally} variants={variants} />
      <p className="text-xs text-ink-2">
        The panel chose <em>between</em> both headlines. Real readers usually
        see only one, so this is a preference share, not a predicted
        click-through rate — and it is unvalidated where two variants say the
        same thing differently.
      </p>
      <PanelCard result={result} />
      {analystMode === "live" && <SummaryCard analyst={analyst} />}
      <VoteList votes={result.votes} />
      {analystMode === "live" ? (
        <AnalystDock analyst={analyst} />
      ) : (
        <p className="text-sm text-ink-2">
          The analyst answers questions about your own tests, spending from a
          signed-in account&rsquo;s daily budget — so the sample keeps it
          closed. Run your own test to ask it; this report is complete as it
          stands.
        </p>
      )}
    </section>
  );
}
