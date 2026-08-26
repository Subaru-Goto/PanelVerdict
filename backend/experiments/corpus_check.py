"""Does the corpus actually serve a reader? 018/#124.

Two stages, because they answer different questions and only the second is the
bar this ticket set:

- **retrieval** — question to expected-section pairs, declared below before any
  run. Cheap, and it proves only that the right passage came back.
- **judged** — a model answers from the retrieved passages and nothing else, and
  a second model scores whether the answer is faithful to them and whether a
  non-expert was served. "The right chunk came back" is not evidence this ticket
  succeeded; 018 says so in as many words, and this is where judge-based tooling
  finally earns its place, having been the wrong instrument twice before.

The judged half answers from the passages directly rather than through the whole
analyst agent. That isolates the question this ticket owns — is a corpus passage
enough to serve a reader — from the agent's tool-routing, which is 012's. An agent
run would confound the two, and a failure would not say which half broke.

Pairs are written here rather than derived from the corpus, so a document that
stops answering its question fails rather than moving the target with it.
"""

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import psycopg
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel, Field

from app.analyst import ToolDeps, stream_analyst
from app.config import settings
from app.pipeline import PanelCounts
from app.schemas import EvaluateResponse, TargetQuery, VoteTally
from app.verdict import panel_verdict
from app.corpus import search_corpus
from app.llm import OpenRouterEmbedder, analyst_chat_model
from app.persistence import prepare_connection


@dataclass(frozen=True)
class Pair:
    """One question and the section that should answer it.

    `asked_as` is how a reader would really type it — off the report, in their own
    words, sometimes with the jargon and sometimes without. That mix is the point:
    the two halves of the hybrid are meant to cover different registers, and pairs
    written only in corpus vocabulary would never test the dense half.
    """

    asked_as: str
    expect_section: str


PAIRS: tuple[Pair, ...] = (
    # The question this ticket is judged on, in both vocabularies: "no call at this
    # credibility" is what the report shows, "undecided" is what people say.
    Pair(
        "B is ahead — why does it say no call?",
        "Why being ahead is not the same as a clear lead",
    ),
    Pair(
        "B is ahead — why is this undecided?",
        "Why being ahead is not the same as a clear lead",
    ),
    Pair(
        "what does practical tie mean",
        "What the report can answer, and what each answer means",
    ),
    Pair(
        "is a tie a failed test",
        "What the report can answer, and what each answer means",
    ),
    Pair(
        "what does panel leans clearly mean",
        "What the report can answer, and what each answer means",
    ),
    Pair("what is a credible interval", "Why the answer is a range and not one number"),
    Pair(
        "why is the answer a range instead of one number",
        "Why the answer is a range and not one number",
    ),
    Pair("what is the tie zone", "The tie zone, and why there is one"),
    Pair("why did the run stop early", "Why a run can stop before everyone has voted"),
    Pair(
        "if nothing was found, how big could the difference be",
        "What a no-call still tells you",
    ),
    # The panel half.
    Pair("are the panelists real people", "Every panelist is invented"),
    Pair("what does high openness mean", "What a trait level says about one panelist"),
    Pair(
        "does openness depend on which country they are from",
        "What the traits are conditioned on, and what that rules out",
    ),
    Pair("what can this test not tell me", "What this panel cannot tell you"),
    # Declared with no expected section, on the assumption that a question outside
    # the product's scope retrieves nothing. **The first run showed the assumption
    # wrong, not the retrieval** — both are questions the corpus deliberately
    # answers, by saying what the panel measures and what it cannot show. Corrected
    # after the fact and recorded rather than quietly re-labelled.
    Pair(
        "what is the click-through rate for this headline",
        "What the panel is actually measuring",
    ),
    Pair("how do I write a better headline", "What this panel cannot tell you"),
)


_JUDGE_PROMPT = """\
You are grading one answer written for somebody who is not a statistician and \
cannot see the product's source code.

You are given the reader's question, the passages the answer was allowed to use, \
and the answer.

Score two things independently.

faithful — does the answer say only what the passages support? An answer that \
adds a plausible-sounding claim the passages do not make is NOT faithful, however \
correct it sounds. An answer that declines because the passages do not cover the \
question IS faithful.

plain — would a non-expert be served? Jargon left unexplained, or an answer that \
restates the question, is not plain. A short honest "the material here does not \
cover that" IS plain.

Answer with the two booleans and one sentence saying what decided the lower of \
the two."""


_ANSWER_PROMPT = """\
Answer the reader's question using ONLY the passages below. They are writing to \
somebody who is not a statistician and cannot see any source code.

If the passages do not cover the question, say so in one sentence and stop. Do \
not fall back on what you know: this product's answers differ from the textbook \
ones, and the reader has no way to catch the difference.

Do not invent any number. The passages deliberately contain none."""


class Grade(BaseModel):
    """Two independent judgements about one answer."""

    faithful: bool = Field(description="Says only what the passages support.")
    plain: bool = Field(description="A non-expert is actually served.")
    because: str = Field(description="One sentence on whichever scored lower.")


def run_judged(
    conn, embedder, answerer, judge, pairs: tuple[Pair, ...], rows: list[dict]
) -> None:
    """Stage two: was the reader served, and only from what we retrieved?

    Appends into the caller's list, for `run_retrieval`'s reason — this stage is
    three paid calls a pair, so losing the lot to a 429 on the last one is the
    expensive version of the same mistake.
    """
    for pair in pairs:
        found = search_corpus(conn, pair.asked_as, embedder)
        passages = "\n\n".join(f"[{p.citation}]\n{p.passage}" for p in found)
        answer = str(
            answerer.invoke(
                [
                    ("system", _ANSWER_PROMPT),
                    ("human", f"Question: {pair.asked_as}\n\nPassages:\n{passages}"),
                ]
            ).content
        )
        grade = judge.invoke(
            [
                ("system", _JUDGE_PROMPT),
                (
                    "human",
                    f"Question: {pair.asked_as}\n\nPassages:\n{passages or '(none)'}"
                    f"\n\nAnswer:\n{answer}",
                ),
            ]
        )
        rows.append(
            {
                "asked_as": pair.asked_as,
                "retrieved": [p.citation for p in found],
                "answer": answer,
                "faithful": grade.faithful,
                "plain": grade.plain,
                "because": grade.because,
            }
        )


def format_judged(rows: list[dict]) -> str:
    faithful = sum(1 for row in rows if row["faithful"])
    plain = sum(1 for row in rows if row["plain"])
    lines = [f"judged: faithful {faithful}/{len(rows)}, plain {plain}/{len(rows)}"]
    for row in rows:
        if not (row["faithful"] and row["plain"]):
            flags = ("" if row["faithful"] else "unfaithful ") + (
                "" if row["plain"] else "unplain"
            )
            lines.append(f"  {flags.strip():<12} {row['asked_as']!r}: {row['because']}")
    return "\n".join(lines)


def run_retrieval(conn, embedder, pairs: tuple[Pair, ...], rows: list[dict]) -> None:
    """Stage one: did the right section come back, and did the corpus decline?

    Appends into a list the caller owns, so a failure part-way through leaves the
    pairs already paid for in the caller's hands. Returning a local list meant the
    assignment never happened and the whole run's results went with the exception —
    which is what the salvage block below exists to prevent.
    """
    for pair in pairs:
        found = search_corpus(conn, pair.asked_as, embedder)
        sections = [passage.section for passage in found]
        rows.append(
            {
                "asked_as": pair.asked_as,
                "expect_section": pair.expect_section,
                "sections": sections,
                # An empty expectation means the corpus should return nothing at
                # all. Scored as a hit only when it returns nothing — a near-miss
                # here is the failure the lexical gate exists to prevent.
                "hit": (not sections)
                if not pair.expect_section
                else pair.expect_section in sections,
                "rank": (
                    sections.index(pair.expect_section) + 1
                    if pair.expect_section in sections
                    else None
                ),
            }
        )


def format_retrieval(rows: list[dict]) -> str:
    hits = [row for row in rows if row["hit"]]
    ranked = [row["rank"] for row in hits if row["rank"]]
    lines = [
        f"retrieval: {len(hits)}/{len(rows)} pairs hit"
        + (f", top-1 on {sum(1 for r in ranked if r == 1)}" if ranked else ""),
    ]
    for row in rows:
        if not row["hit"]:
            got = ", ".join(row["sections"][:2]) or "nothing"
            lines.append(f"  MISS  {row['asked_as']!r} -> {got}")
    return "\n".join(lines)


# The questions a reader asks that the model has a confident, wrong answer to.
# Routing is its own stage because the corpus being right is worth nothing if the
# analyst never reaches for it — and answering "what is the Big Five" from weights
# is exactly what it did before this corpus existed.
ROUTING_QUESTIONS: tuple[str, ...] = (
    "what is the Big Five?",
    "what does high openness mean?",
    "what is a credible interval?",
    "why is this undecided when B is ahead?",
    "are the panelists real people?",
)

# Asked to check the loophole holds in the other direction: a question about THIS
# run's numbers must still go to a tool that has them, never to the corpus, which
# deliberately holds none.
RUN_QUESTIONS: tuple[str, ...] = (
    "how many panelists voted?",
    "what was the final split?",
)


def _sample_result() -> EvaluateResponse:
    """One finished test for the analyst to be asked about.

    Deliberately an undecided one with B ahead, because that is the situation the
    corpus's headline question describes and the one a reader actually meets.
    """
    tally = VoteTally(counts={"a": 22, "b": 28}, total=50)
    return EvaluateResponse(
        verdict=panel_verdict(preferring_b=28, total=50),
        tally=tally,
        counts=PanelCounts(requested=50, matched=50, voted=50),
        query=TargetQuery(
            countries=("US",),
            coverage="requested",
            min_age=18,
            max_age=99,
            gender=None,
            income_quintiles=(),
            education=(),
            traits=(),
            notices=(),
        ),
        notices=[],
        votes=[],
        variants={"a": "Save 50% today", "b": "Members save half"},
        stop_reason=None,
    )


def run_routing(
    result, deps, model, checkpointer, questions, expect: str, rows: list[dict]
) -> None:
    """Which tools a live turn actually calls. No judge — this is observation.

    Appends into the caller's list, for `run_retrieval`'s reason.
    """
    for i, question in enumerate(questions):
        tools: list[str] = []
        for line in stream_analyst(
            model=model,
            result=result,
            thread_id=f"routing-{expect}-{i}",
            message=question,
            checkpointer=checkpointer,
            deps=deps,
        ):
            event = json.loads(line)
            if event.get("type") == "tool":
                tools.append(event["name"])
        rows.append(
            {
                "question": question,
                "tools": tools,
                "expect": expect,
                "routed": expect in tools,
            }
        )


def format_routing(rows: list[dict]) -> str:
    ok = [row for row in rows if row["routed"]]
    lines = [f"routing: {len(ok)}/{len(rows)} turns reached the expected tool"]
    for row in rows:
        mark = "  ok  " if row["routed"] else " MISS "
        lines.append(f"{mark}{row['question']!r} -> {row['tools'] or 'no tool at all'}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--part",
        choices=("retrieval", "judged", "routing"),
        default="retrieval",
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model", default=settings.analyst_model)
    parser.add_argument("--judge-model", default=settings.judge_model)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    # One embedding per question for retrieval; the judged half adds an answer
    # and a grading call each. Written as a derivation so adding a pair cannot
    # leave a figure here wrong.
    if args.part == "routing":
        turns = len(ROUTING_QUESTIONS) + len(RUN_QUESTIONS)
        print(f"routing: {turns} live analyst turns, each a few calls.")
    else:
        calls = len(PAIRS) * (1 if args.part == "retrieval" else 3)
        print(f"{args.part}: {calls} paid calls over {len(PAIRS)} pairs.")
    if args.dry_run:
        return
    if settings.openrouter_api_key is None:
        raise SystemExit("openrouter_api_key is not set; cannot embed the questions.")

    embedder = OpenRouterEmbedder(
        api_key=settings.openrouter_api_key.get_secret_value(),
        base_url=settings.openrouter_base_url,
        model=settings.embedding_model,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    try:
        with psycopg.connect(settings.database_url, autocommit=True) as conn:
            prepare_connection(conn)
            if args.part == "routing":
                chat = analyst_chat_model(
                    api_key=settings.openrouter_api_key.get_secret_value(),
                    base_url=settings.openrouter_base_url,
                    model=args.model,
                )
                deps = ToolDeps(conn=conn, embedder=embedder)
                saver = InMemorySaver()
                run_routing(
                    _sample_result(),
                    deps,
                    chat,
                    saver,
                    ROUTING_QUESTIONS,
                    "explain_the_report",
                    rows,
                )
                run_routing(
                    _sample_result(),
                    deps,
                    chat,
                    saver,
                    RUN_QUESTIONS,
                    "analyze_results",
                    rows,
                )
            elif args.part == "retrieval":
                run_retrieval(conn, embedder, PAIRS, rows)
            else:
                # A separate client on `judge_model`, not the answerer rebound.
                # One instance grading its own output is the configuration
                # guaranteed to share every blind spot with the thing under test —
                # and it did: the first run scored an answer faithful that
                # described a verdict rule the product had abandoned.
                answerer = analyst_chat_model(
                    api_key=settings.openrouter_api_key.get_secret_value(),
                    base_url=settings.openrouter_base_url,
                    model=args.model,
                )
                judge = analyst_chat_model(
                    api_key=settings.openrouter_api_key.get_secret_value(),
                    base_url=settings.openrouter_base_url,
                    model=args.judge_model,
                ).with_structured_output(Grade)
                run_judged(conn, embedder, answerer, judge, PAIRS, rows)
    finally:
        # Paid calls that do not reproduce: a failure on the last pair must not
        # also cost the report for every pair before it.
        if rows:
            args.out.write_text("\n".join(json.dumps(row) for row in rows))
            print(
                format_retrieval(rows)
                if args.part == "retrieval"
                else format_routing(rows)
                if args.part == "routing"
                else format_judged(rows)
            )


if __name__ == "__main__":
    main()
