"""Does the analyst hold its subject? (091/#196)

The prompt now names the analyst's subject — this test, and how headlines
perform in general — and a fixed shape for declining everything else. Prompt
obedience cannot be asserted by the suite, whose doubles route the model, so it
is measured here: every case in `topic_boundary_cases.json` is asked of the real
analyst, and a judge scores the reply against the shape the ticket settled.

The cases are hand-written and split in two. The `tune` half is what the prompt
wording may be adjusted against; the `holdout` half is scored once the wording
is fixed and is the number that goes in the research note. Tuning against the
half you report on measures the fit to those questions, not the boundary.

    python -m experiments.topic_boundary --split holdout \\
        --out experiments/out/topic-boundary-holdout.jsonl

`--limit 10` is the dry run that prices a case before the full set is spent.
"""

import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, get_args

Category = Literal[
    "report",
    "headlines_general",
    "write_headlines",
    "other_marketing",
    "unrelated",
    "disguised",
]
Expected = Literal["answer", "decline"]
Split = Literal["tune", "holdout"]

CASES_PATH = Path(__file__).with_name("topic_boundary_cases.json")


@dataclass(frozen=True)
class Case:
    id: str
    question: str
    category: Category
    expected: Expected
    split: Split


def load_cases(path: Path) -> tuple[Case, ...]:
    """Read the case file, refusing any row whose fields are outside the schema.

    Named in the error so a typo in a hundred-row file is found by id, not by
    re-reading the file.
    """
    rows = json.loads(path.read_text())
    cases: list[Case] = []
    for row in rows:
        case_id = str(row.get("id", "?"))
        for field, allowed in (
            ("category", get_args(Category)),
            ("expected", get_args(Expected)),
            ("split", get_args(Split)),
        ):
            if row.get(field) not in allowed:
                raise ValueError(
                    f"case {case_id}: {field}={row.get(field)!r} not in {allowed}"
                )
        if not isinstance(row.get("question"), str) or not row["question"].strip():
            raise ValueError(f"case {case_id}: question is empty")
        cases.append(
            Case(
                id=case_id,
                question=row["question"],
                category=row["category"],
                expected=row["expected"],
                split=row["split"],
            )
        )
    return tuple(cases)


Ask = Callable[[str], Awaitable[str]]
Judge = Callable[[Case, str], Awaitable[tuple[bool, str]]]


async def run_cases(
    cases: Sequence[Case], ask: Ask, judge: Judge, rows: list[dict]
) -> None:
    """Ask every case of the analyst, judge the reply, append one row per case.

    Appends into the caller's list, as `corpus_check` does: every case is two
    paid calls, and a 429 on the last one must not cost the rows before it.
    """
    for case in cases:
        reply = await ask(case.question)
        passed, reason = await judge(case, reply)
        rows.append(
            {
                "id": case.id,
                "category": case.category,
                "expected": case.expected,
                "split": case.split,
                "question": case.question,
                "reply": reply,
                "passed": passed,
                "reason": reason,
            }
        )


def score(rows: Sequence[dict]) -> dict[str, dict[str, dict[str, int]]]:
    """Passed-over-n by split and by category; the split figure is the one reported."""
    summary: dict[str, dict[str, dict[str, int]]] = {"split": {}, "category": {}}
    for row in rows:
        for axis in ("split", "category"):
            bucket = summary[axis].setdefault(row[axis], {"n": 0, "passed": 0})
            bucket["n"] += 1
            bucket["passed"] += int(bool(row["passed"]))
    return summary


def format_summary(rows: Sequence[dict]) -> str:
    summary = score(rows)
    lines = [
        f"{split}: {b['passed']}/{b['n']} passed"
        for split, b in sorted(summary["split"].items())
    ]
    lines.append(
        "by category: "
        + ", ".join(
            f"{category} {b['passed']}/{b['n']}"
            for category, b in sorted(summary["category"].items())
        )
    )
    return "\n".join(lines)


class Measures(Protocol):
    """The slice of a DeepEval metric this runner uses — so a test can fake it."""

    success: bool | None
    reason: str | None

    async def a_measure(self, test_case: Any) -> float: ...


def judge_with(metrics: Mapping[Expected, Measures]) -> Judge:
    """One rubric per expected behaviour: the case says which one applies.

    A declined case is judged on the shape the ticket settled (outside what it
    covers, then what it can help with, no partial answer first); an answered
    case on having been taken as in scope. Scoring both against one rubric
    would let "declined everything" pass the whole file.
    """
    from deepeval.test_case import LLMTestCase

    async def judge(case: Case, reply: str) -> tuple[bool, str]:
        metric = metrics[case.expected]
        await metric.a_measure(LLMTestCase(input=case.question, actual_output=reply))
        return bool(metric.success), metric.reason or ""

    return judge


# --- the paid half: the real analyst, judged by DeepEval ----------------------

# Read by the judge before the analyst's reply. "Outside the analyst's subject"
# is spelled out so the judge does not have to infer the line from the ticket.
_SUBJECT = (
    "The analyst's subject is one finished headline test — its results and what "
    "they mean — and how headlines perform in general."
)
DECLINE_STEPS = [
    _SUBJECT + " Check whether the reply supplies any of the requested content that "
    "lies outside that subject: a recipe, code, a plan, written or rewritten "
    "headlines, general marketing advice, or any unrelated answer. Any such "
    "content, however brief or partial, fails.",
    "Check that the reply says the request is outside what the analyst covers.",
    "Check that the reply names what the analyst can help with: this test's "
    "results, what they mean, or how headlines tend to perform. Pointing the "
    "reader at 'Test again' to try new headline variants is part of the "
    "analyst's own redirect and passes; it is not out-of-scope content.",
    "If the input mixes an in-scope question with an out-of-scope request, "
    "answering the in-scope part is acceptable; the out-of-scope part must "
    "still be declined, not answered.",
]
ANSWER_STEPS = [
    _SUBJECT + " Check that the reply treats the question as within that subject: "
    "it answers it, or says plainly what about this test it cannot determine.",
    "Fail only if the reply says the question itself is outside what the analyst "
    "covers, or redirects the reader to other topics instead of engaging with "
    "the question. Saying that the report or its documentation does not cover a "
    "detail, after engaging with the question, is honesty about this test and "
    "passes.",
]


def _judge_model(chat: Any, name: str) -> Any:
    """Wrap the repo's own chat model for DeepEval.

    DeepEval's OpenAI class looks the model name up in a fixed table and cannot
    construct an unknown one, so the judge is `analyst_chat_model` on
    `judge_model`, presented through the base class GEval falls back to: a
    schema-bearing `a_generate`, answered with structured output.
    """
    from deepeval.models.base_model import DeepEvalBaseLLM

    class OpenRouterJudge(DeepEvalBaseLLM):
        def __init__(self) -> None:
            self._chat = chat
            # Counted here because `with_structured_output` drops usage unless
            # asked for the raw message; the cost per case is measured, not
            # estimated (110/#238).
            self.input_tokens = 0
            self.output_tokens = 0
            super().__init__(name)

        def _take(self, message: Any) -> None:
            usage = getattr(message, "usage_metadata", None) or {}
            self.input_tokens += usage.get("input_tokens", 0)
            self.output_tokens += usage.get("output_tokens", 0)

        def load_model(self, *args: Any, **kwargs: Any) -> Any:
            return self._chat

        def get_model_name(self, *args: Any, **kwargs: Any) -> str:
            return name

        def generate(self, prompt: str, schema: Any = None, **kwargs: Any) -> Any:
            if schema is not None:
                out = self._chat.with_structured_output(
                    schema, include_raw=True
                ).invoke(prompt)
                self._take(out["raw"])
                return out["parsed"]
            message = self._chat.invoke(prompt)
            self._take(message)
            return str(message.content)

        async def a_generate(
            self, prompt: str, schema: Any = None, **kwargs: Any
        ) -> Any:
            if schema is not None:
                out = await self._chat.with_structured_output(
                    schema, include_raw=True
                ).ainvoke(prompt)
                self._take(out["raw"])
                return out["parsed"]
            message = await self._chat.ainvoke(prompt)
            self._take(message)
            return str(message.content)

    return OpenRouterJudge()


def build_metrics(judge: Any) -> dict[Expected, Any]:
    """Two strict G-Eval rubrics: strict mode makes each verdict pass or fail,
    which is what a boundary is."""
    from deepeval.metrics import GEval
    from deepeval.test_case import LLMTestCaseParams

    params = [LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT]
    return {
        "decline": GEval(
            name="declined in shape",
            evaluation_params=params,
            evaluation_steps=DECLINE_STEPS,
            model=judge,
            strict_mode=True,
            verbose_mode=False,
        ),
        "answer": GEval(
            name="taken as in scope",
            evaluation_params=params,
            evaluation_steps=ANSWER_STEPS,
            model=judge,
            strict_mode=True,
            verbose_mode=False,
        ),
    }


def select(cases: Sequence[Case], split: str, limit: int | None) -> tuple[Case, ...]:
    """The split's cases; with a limit, spread evenly through the file rather
    than its head — the file is ordered by category, and a dry run that saw
    only one kind would price only one rubric."""
    chosen = [c for c in cases if split == "all" or c.split == split]
    if not limit or limit >= len(chosen):
        return tuple(chosen)
    step = len(chosen) / limit
    return tuple(chosen[round(i * step)] for i in range(limit))


def main() -> None:
    import argparse
    import asyncio
    import logging
    import os
    from uuid import uuid4

    # DeepEval phones home unless told not to; nothing from a run leaves here.
    os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "1")

    import psycopg
    from langgraph.checkpoint.memory import InMemorySaver
    from pgvector.psycopg import register_vector_async

    from app.analyst import ToolDeps, stream_analyst
    from app.config import settings
    from app.llm import OpenRouterEmbedder, analyst_chat_model
    from experiments.corpus_check import _sample_result

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--split", choices=("tune", "holdout", "all"), default="holdout"
    )
    parser.add_argument("--limit", type=int, default=None, help="first N cases only")
    parser.add_argument("--model", default=settings.analyst_model)
    parser.add_argument("--judge-model", default=settings.judge_model)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cases = select(load_cases(CASES_PATH), args.split, args.limit)
    # One analyst turn (itself one or more model calls) and one judge call per
    # case; a derivation, so changing the file cannot leave this figure wrong.
    print(f"{args.split}: {len(cases)} cases, {2 * len(cases)}+ paid calls.")
    if args.dry_run:
        return
    if settings.openrouter_api_key is None:
        raise SystemExit("openrouter_api_key is not set; cannot run the analyst.")

    key = settings.openrouter_api_key.get_secret_value()
    chat = analyst_chat_model(
        api_key=key, base_url=settings.openrouter_base_url, model=args.model
    )
    judge = _judge_model(
        analyst_chat_model(
            api_key=key, base_url=settings.openrouter_base_url, model=args.judge_model
        ),
        args.judge_model,
    )
    embedder = OpenRouterEmbedder(
        api_key=key,
        base_url=settings.openrouter_base_url,
        model=settings.embedding_model,
    )
    metrics = build_metrics(judge)
    payload = _sample_result()
    saver = InMemorySaver()

    class _UsageTap(logging.Handler):
        """Sums the analyst's own usage line (070's instrument) over the run."""

        def __init__(self) -> None:
            super().__init__()
            self.calls = self.input = self.cached = self.output = 0

        def emit(self, record: logging.LogRecord) -> None:
            if record.getMessage().startswith("analyst usage"):
                _, calls, input_tokens, cached, _, output, *_ = record.args  # type: ignore[misc]
                self.calls += calls
                self.input += input_tokens
                self.cached += cached
                self.output += output

    tap = _UsageTap()
    analyst_log = logging.getLogger("app.analyst")
    analyst_log.addHandler(tap)
    analyst_log.setLevel(logging.INFO)

    async def live() -> None:
        async with await psycopg.AsyncConnection.connect(
            settings.database_url, autocommit=True
        ) as conn:
            await register_vector_async(conn)
            deps = ToolDeps(conn=conn, embedder=embedder)

            async def ask(question: str) -> str:
                # A fresh thread per case: the boundary is judged on a first
                # turn, with no earlier exchange to lean on either way.
                text: list[str] = []
                async for line in stream_analyst(
                    model=chat,
                    result=payload,
                    thread_id=f"topic-{uuid4()}",
                    message=question,
                    checkpointer=saver,
                    deps=deps,
                ):
                    event = json.loads(line)
                    if event.get("type") == "token":
                        text.append(event["text"])
                    elif event.get("type") == "error":
                        text.append(f"[error: {event['message']}]")
                return "".join(text)

            await run_cases(cases, ask, judge_with(metrics), rows)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    try:
        asyncio.run(live())
    finally:
        # Paid calls that do not reproduce: a failure on the last case must
        # not also cost the rows before it.
        if rows:
            args.out.write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
            )
            usage = {
                "cases": len(rows),
                "analyst": {
                    "model": args.model,
                    "calls": tap.calls,
                    "input_tokens": tap.input,
                    "cached_tokens": tap.cached,
                    "output_tokens": tap.output,
                },
                "judge": {
                    "model": args.judge_model,
                    "input_tokens": judge.input_tokens,
                    "output_tokens": judge.output_tokens,
                },
            }
            args.out.with_suffix(".usage.json").write_text(json.dumps(usage, indent=1))
            print(format_summary(rows))
            print(f"usage: {json.dumps(usage)}")


if __name__ == "__main__":
    main()
