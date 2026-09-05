"""The analyst's RAG, measured with Ragas (110/#238): faithfulness, context
precision and context recall over hand-written questions.

Each case is one real analyst turn — the same `stream_analyst` a reader gets —
asked on a fresh thread about a fixture report. What the turn retrieved is read
back off its checkpointed transcript (the corpus tool's JSON result); the reply
is the response; the hand-written `reference` and the named corpus passage are
the ground truth. Three Ragas metrics score each case, judged by the repo's own
`judge_model` through OpenRouter.

Paid, on demand, never in CI (decision Q1). Cost is measured, not estimated:
the analyst's own `analyst usage` log line is summed, and every judge call's
usage is read off the HTTP response. Results are rows plus a `.usage.json`,
and the record is `docs/research/rag-baseline.md`.

    uv run --with-requirements evals/requirements.txt \\
        python -m experiments.rag_eval --limit 10 --out experiments/out/rag-eval-sample.jsonl
    uv run --with-requirements evals/requirements.txt \\
        python -m experiments.rag_eval --out experiments/out/rag-eval-baseline.jsonl

Ragas is an overlay, not a dependency — see evals/requirements.txt for why.

`--dry-run` prices the run and exits before any client exists.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from app.corpus import Chunk, _all_chunks

CASES_PATH = Path(__file__).with_name("rag_cases.json")

# Three metrics, and Ragas makes at most this many judge calls per case for
# them: faithfulness extracts statements then verdicts them (2), precision
# judges each retrieved passage (up to 4), recall judges the reference (1).
# A ceiling for the dry-run price line; the runs measured ~5 a case (150 calls
# over 30, 43 over 10 — docs/research/rag-baseline.md), so the line reads high.
_JUDGE_CALLS_PER_CASE = 7


@dataclass(frozen=True)
class Case:
    id: str
    source: str
    section: str
    question: str
    reference: str


def load_cases(path: Path = CASES_PATH) -> tuple[Case, ...]:
    raw = json.loads(path.read_text())["cases"]
    return tuple(
        Case(
            id=row["id"],
            source=row["source"],
            section=row["section"],
            question=row["question"],
            reference=row["reference"],
        )
        for row in raw
    )


def _chunk_for(case: Case) -> Chunk:
    for chunk in _all_chunks():
        if (chunk.source, chunk.section) == (case.source, case.section):
            return chunk
    raise KeyError(
        f"{case.id}: no corpus chunk headed {case.section!r} in {case.source!r}"
    )


def reference_context(case: Case) -> str:
    """The passage the answer should have drawn on, as the corpus stores it."""
    return _chunk_for(case).passage


def searched_for(messages: Sequence[BaseMessage]) -> list[str]:
    """The strings the analyst searched the corpus with during one turn, in order.

    The analyst rewrites the reader's question before it searches, so a miss can
    only be diagnosed against what it actually asked the retriever (129/#313).
    """
    return [
        str(call["args"].get("question", ""))
        for message in messages
        if isinstance(message, AIMessage)
        for call in message.tool_calls
        if call["name"] == "explain_the_report"
    ]


def why_unscored(*, searched: Sequence[str], retrieved: Sequence[str]) -> str | None:
    """Why a turn has no grounding to judge, or None when it has some.

    "never searched" is routing: the analyst answered from the report's tools.
    "nothing passed the gate" is retrieval: it searched, and the corpus's
    lexical gate returned no passage (129/#313 — the two were one label before).
    """
    if retrieved:
        return None
    return "nothing passed the gate" if searched else "never searched"


def retrieved_passages(messages: Sequence[BaseMessage]) -> list[str]:
    """The passages the corpus tool handed the model during one turn, in order.

    Read off the transcript rather than re-run: what Ragas judges must be what
    the analyst actually saw. A turn that never called the tool retrieved
    nothing, and that is a finding of its own (see why_unscored), not an error here.
    """
    passages: list[str] = []
    for message in messages:
        if isinstance(message, ToolMessage) and message.name == "explain_the_report":
            for item in json.loads(str(message.content)):
                passages.append(item["passage"])
    return passages


def select(cases: Sequence[Case], limit: int | None) -> tuple[Case, ...]:
    """All cases, or `limit` of them spread evenly through the file — it is
    ordered by document, and a sample that saw only one would price only one."""
    if not limit or limit >= len(cases):
        return tuple(cases)
    step = len(cases) / limit
    return tuple(cases[round(i * step)] for i in range(limit))


def main() -> None:
    import argparse
    import asyncio
    import logging
    from uuid import uuid4

    from app.config import settings

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--limit", type=int, default=None, help="N cases, spread across the file"
    )
    parser.add_argument("--model", default=settings.analyst_model)
    parser.add_argument("--judge-model", default=settings.judge_model)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cases = select(load_cases(), args.limit)
    print(
        f"{len(cases)} cases: one analyst turn each (1+ paid calls) and up to "
        f"{_JUDGE_CALLS_PER_CASE} judge calls each — about "
        f"{len(cases) * (1 + _JUDGE_CALLS_PER_CASE)} paid calls."
    )
    if args.dry_run:
        return
    if settings.openrouter_api_key is None:
        raise SystemExit(
            "openrouter_api_key is not set; cannot run the analyst or the judge."
        )

    # Past the free exits: the clients, and the only Ragas imports a run needs.
    import httpx
    import openai
    import psycopg
    from langgraph.checkpoint.memory import InMemorySaver
    from ragas.llms import llm_factory
    from ragas.metrics.collections import ContextPrecision, ContextRecall, Faithfulness

    from app.analyst import ToolDeps, stream_analyst
    from app.llm import OpenRouterEmbedder, analyst_chat_model
    from experiments.corpus_check import sample_result
    from experiments.topic_boundary import AnalystUsageTap, write_run

    key = settings.openrouter_api_key.get_secret_value()
    chat = analyst_chat_model(
        api_key=key, base_url=settings.openrouter_base_url, model=args.model
    )
    embedder = OpenRouterEmbedder(
        api_key=key,
        base_url=settings.openrouter_base_url,
        model=settings.embedding_model,
    )

    # The judge's usage, read off every response body: Ragas reports scores,
    # not tokens, and the cost per case is measured rather than estimated.
    judge_usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}

    async def _count(response: httpx.Response) -> None:
        await response.aread()
        try:
            usage = response.json().get("usage") or {}
        except ValueError:
            return
        judge_usage["calls"] += 1
        judge_usage["input_tokens"] += int(usage.get("prompt_tokens", 0))
        judge_usage["output_tokens"] += int(usage.get("completion_tokens", 0))

    client = openai.AsyncOpenAI(
        api_key=key,
        base_url=settings.openrouter_base_url,
        http_client=httpx.AsyncClient(event_hooks={"response": [_count]}),
    )
    judge = llm_factory(args.judge_model, client=client)
    metrics = {
        "faithfulness": Faithfulness(llm=judge),
        "context_precision": ContextPrecision(llm=judge),
        "context_recall": ContextRecall(llm=judge),
    }

    payload = sample_result()
    saver = InMemorySaver()
    tap = AnalystUsageTap()
    analyst_log = logging.getLogger("app.analyst")
    analyst_log.addHandler(tap)
    analyst_log.setLevel(logging.INFO)
    rows: list[dict[str, Any]] = []

    async def live() -> None:
        async with await psycopg.AsyncConnection.connect(
            settings.database_url, autocommit=True
        ) as conn:
            deps = ToolDeps(conn=conn, embedder=embedder)
            for case in cases:
                thread = f"rag-{uuid4()}"
                text: list[str] = []
                async for line in stream_analyst(
                    owner="experiment",
                    model=chat,
                    result=payload,
                    thread_id=thread,
                    message=case.question,
                    checkpointer=saver,
                    deps=deps,
                ):
                    event = json.loads(line)
                    if event.get("type") == "token":
                        text.append(event["text"])
                    elif event.get("type") == "error":
                        text.append(f"[error: {event['message']}]")
                reply = "".join(text)
                # The transcript is keyed as stream_analyst keys it (035/#136).
                state = saver.get_tuple(
                    {"configurable": {"thread_id": f"experiment:{thread}"}}
                )
                messages = (
                    state.checkpoint["channel_values"].get("messages", [])
                    if state
                    else []
                )
                retrieved = retrieved_passages(messages)
                searched = searched_for(messages)
                row: dict[str, Any] = {
                    "id": case.id,
                    "question": case.question,
                    "reply": reply,
                    "searched": searched,
                    "retrieved": retrieved,
                    "reference_section": case.section,
                }
                unscored = why_unscored(searched=searched, retrieved=retrieved)
                if unscored:
                    row["unscored"] = unscored
                    rows.append(row)
                    continue
                reference = case.reference
                row["faithfulness"] = (
                    await metrics["faithfulness"].ascore(
                        user_input=case.question,
                        response=reply,
                        retrieved_contexts=retrieved,
                    )
                ).value
                row["context_precision"] = (
                    await metrics["context_precision"].ascore(
                        user_input=case.question,
                        reference=reference,
                        retrieved_contexts=retrieved,
                    )
                ).value
                row["context_recall"] = (
                    await metrics["context_recall"].ascore(
                        user_input=case.question,
                        reference=reference,
                        retrieved_contexts=retrieved,
                    )
                ).value
                row["reference_retrieved"] = any(
                    p.startswith(f"{case.source} — {case.section}") for p in retrieved
                )
                rows.append(row)
                print(f"{case.id}: { {k: round(row[k], 2) for k in metrics} }")

    try:
        asyncio.run(live())
    finally:
        if rows:
            scored = [r for r in rows if "faithfulness" in r]
            if scored:
                for name in ("faithfulness", "context_precision", "context_recall"):
                    values = [r[name] for r in scored if r.get(name) is not None]
                    print(
                        f"{name}: mean {sum(values) / len(values):.3f} over {len(values)}"
                    )
                hits = sum(1 for r in scored if r["reference_retrieved"])
                print(
                    f"reference passage retrieved in {hits}/{len(scored)} scored cases"
                )
            for reason in ("never searched", "nothing passed the gate"):
                count = sum(1 for r in rows if r.get("unscored") == reason)
                if count:
                    print(f"{count} case(s) unscored: {reason}")
            write_run(
                args.out,
                rows,
                analyst_model=args.model,
                tap=tap,
                judge_model=args.judge_model,
                judge_usage=judge_usage,
            )


if __name__ == "__main__":
    main()
