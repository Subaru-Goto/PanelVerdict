"""Enacted-context check (095): do a customer's own words move a panel, safely?

094 wants the free-text audience field **enacted** — inserted into every
panelist's vote prompt on top of the surveyed demographics — because the pool
holds age, gender, education and income and cannot serve "parents" or "shops
online". Two things have to be true before that ships, and this measures both
with 014's instrument rather than a new one.

Run it in three stages; the first two are free:

    python -m experiments.enacted_context --part effect --replicates 6 --dry-run
    python -m experiments.enacted_context --part screen --out out/screen.jsonl
    python -m experiments.enacted_context --part effect --replicates 6 \
        --out experiments/out/enacted-effect.jsonl
    python -m experiments.enacted_context --part attack --replicates 4 \
        --out experiments/out/enacted-attack.jsonl
    python -m experiments.enacted_analysis experiments/out/enacted-*.jsonl

`screen` runs first on purpose: an attack the screener already refuses never
reaches a panel, and knowing which ones those are is what the vote rows are read
against.
"""

import argparse
import json
import secrets
from collections.abc import Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Literal
from pathlib import Path

from app.bigfive import bigfive_from_levels
from app.config import settings
from app.llm import OpenRouterPanelLLM, build_vote_messages
from app.panel import render_persona_prompt
from app.schemas import Persona, TraitLevel
from langchain_core.messages import BaseMessage
from app.screening import OpenRouterScreener, Screener
from app.vote import PanelLLM
from experiments.design import (
    DEFAULT_FRAMING,
    HIGH,
    LOW,
    ORDERS,
    TRAITS,
    HeadlinePair,
    VoteRow,
    write_rows,
)
from experiments.enacted_design import (
    ATTACKS,
    BASELINE,
    CONTEXTS,
    ENACTED,
    BORROWED,
    PAIRS,
    EnactedContext,
    render_enacted,
)
from experiments.manipulation_check import Cell, vote_cell

# Where the customer's words are put, which is the thing 095's second half is
# actually comparing:
#
#   fenced — in the system prompt, inside a nonce block framed as a description
#   bare   — in the system prompt, spliced in as if we had written it (ablation)
#   human  — in the task message, inside the fence the headlines already have
Rendering = Literal["fenced", "bare", "human"]

_DEFAULT_WORKERS = 8

# Temperament held at MEDIUM throughout: this check asks what the *words* do, and
# a swept trait would be a second manipulation in the same prompt. What varies
# instead is the demographics the words sit on top of — three people rather than
# one, so a result is not a fact about a single 42-year-old.
_MEDIUM = {trait: TraitLevel.MEDIUM for trait in TRAITS}

BASE_PERSONAS: tuple[Persona, ...] = (
    Persona(
        id="p-42f",
        country="US",
        age=42,
        gender="female",
        income_quintile=3,
        education="secondary",
        big_five=bigfive_from_levels(**_MEDIUM),
    ),
    Persona(
        id="p-29m",
        country="US",
        age=29,
        gender="male",
        income_quintile=4,
        education="tertiary",
        big_five=bigfive_from_levels(**_MEDIUM),
    ),
    Persona(
        id="p-58f",
        country="US",
        age=58,
        gender="female",
        income_quintile=2,
        education="below_secondary",
        big_five=bigfive_from_levels(**_MEDIUM),
    ),
)


class HumanTurnPanelLLM(OpenRouterPanelLLM):
    """The shipped adapter with the enacted words in the human turn instead.

    The third placement, and the one this codebase argues for elsewhere:
    `app/screening.py` says untrusted text is the human turn and never the system
    one, and the headlines — the other untrusted channel — are already fenced
    there. The words ride inside that same fence rather than getting a second.

    A subclass over the real adapter, not a re-implementation: the timeouts, the
    structured output, the 402 handling and the scaffold are the things under
    test, so an arm that rebuilt them would be measuring a different client.

    The persona prompt reaching `vote` carries no context at all in this arm —
    `plan_cells` renders it with `placement="human"`, which leaves it alone.
    """

    def __init__(self, *, enacted: str, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._enacted = enacted

    def _messages(
        self, system_prompt: str, option_1: str, option_2: str
    ) -> list[BaseMessage]:
        return build_vote_messages(
            system_prompt,
            option_1,
            option_2,
            question=self._question,
            enacted=self._enacted,
            nonce=self._nonce,
        )


def plan_cells(
    *,
    contexts: tuple[EnactedContext, ...],
    pairs: tuple[HeadlinePair, ...],
    replicates: int,
    rendering: Rendering,
    nonce: str,
    personas: tuple[Persona, ...] = BASE_PERSONAS,
) -> list[Cell]:
    """Enumerate every (context × persona × pair × replicate × order) cell.

    Rectangular by construction, because 014's flip rate pairs a vote in one arm
    with the same cell in another and refuses to run on an unmatched design.

    `trait` and `level` are labels here rather than manipulations: the analysis
    matches on `trait`, so it stays constant across arms or no two arms would
    ever line up. `level` carries the context's role **and how it was rendered**,
    because the fenced and bare runs are otherwise byte-identical in their output
    — the whole "what the fence buys" comparison would then rest on which
    filename the operator typed.

    `nonce` is required rather than defaulted, for `build_vote_messages`' reason:
    a guessable delimiter is a forgeable one, and a caller that forgets should
    fail loudly instead of quietly measuring a fence that was not there.
    """

    cells: list[Cell] = []
    for context in contexts:
        for persona in personas:
            persona_prompt = render_persona_prompt(persona)
            # In the `human` arm the words are not in the system prompt at all —
            # `HumanTurnPanelLLM` puts them in the task, inside the fence the
            # headlines already have.
            prompt = (
                persona_prompt
                if rendering == "human"
                else render_enacted(
                    persona_prompt,
                    context.words,
                    nonce=nonce,
                    fenced=rendering == "fenced",
                )
            )
            for pair in pairs:
                text = {HIGH: pair.predicted_high, LOW: pair.predicted_low}
                for replicate in range(replicates):
                    for order in ORDERS:
                        cells.append(
                            Cell(
                                arm=context.id,
                                framing=DEFAULT_FRAMING.id,
                                trait="enacted",
                                level=f"{context.role}:{rendering}",
                                persona_id=persona.id,
                                pair_id=pair.id,
                                replicate=replicate,
                                order=order,
                                prompt=prompt,
                                options=(text[order[0]], text[order[1]]),
                            )
                        )
    return cells


def collect_rows(
    *,
    llms: Mapping[str, PanelLLM],
    cells: list[Cell],
    workers: int = 1,
    done: list[VoteRow] | None = None,
) -> list[VoteRow]:
    """Vote on every planned cell, in plan order whatever finished first.

    `done` collects rows as they land, so a failure on the last cell of a
    thousand does not throw away the nine hundred already paid for. The returned
    list keeps plan order; `done` is in completion order and is for salvage.
    """
    landed = done if done is not None else []
    missing = sorted({cell.arm for cell in cells} - set(llms))
    if missing:
        raise KeyError(f"no client for arm(s) {missing}; have {sorted(llms)}")

    def one(cell: Cell) -> VoteRow:
        row = vote_cell(llms[cell.arm], cell)
        landed.append(row)
        return row

    if workers == 1:
        return [one(cell) for cell in cells]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(one, cells))


def screen_contexts(
    screener: Screener, contexts: tuple[EnactedContext, ...], *, replicates: int = 1
) -> Iterator[Mapping[str, object]]:
    """Ask the shipped screener about each context, before any panel sees it.

    An attack the screener refuses never reaches a vote prompt, so this decides
    which rows in the attack run are measuring a live threat and which are
    measuring a defence-in-depth that never has to hold.

    Replicated, because the screener is a model at default temperature: asked
    once, a coin-flip screener and a reliable one produce the same file.
    """
    for context in contexts:
        if not context.words:
            continue
        for replicate in range(replicates):
            verdict = screener.screen(context.words)
            yield {
                "id": context.id,
                "role": context.role,
                "replicate": replicate,
                "words": context.words,
                "flagged": verdict.flagged,
                "reason": verdict.reason,
            }


@dataclass(frozen=True)
class Part:
    """One run's design. The two halves of 095 ask different questions, so they
    are not the same design run twice.

    The effect half needs several people and every stimulus, because it asks
    whether words move a *panel*. The attack half needs one person and the two
    borrowed pairs, because it asks whether a vote was hijacked — which the
    comprehension pair answers on its own, and which no amount of demographic
    spread makes more or less true.
    """

    contexts: tuple[EnactedContext, ...]
    pairs: tuple[HeadlinePair, ...]
    personas: int


PARTS: dict[str, Part] = {
    "effect": Part(contexts=(BASELINE, *ENACTED), pairs=PAIRS, personas=3),
    "attack": Part(
        contexts=(BASELINE, *ATTACKS),
        pairs=tuple(pair for pair in PAIRS if pair.id in BORROWED),
        personas=1,
    ),
    "screen": Part(contexts=CONTEXTS, pairs=(), personas=0),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--part", choices=sorted(PARTS), required=True)
    parser.add_argument("--replicates", type=int, default=6)
    parser.add_argument(
        "--rendering",
        choices=("fenced", "bare", "human"),
        default="fenced",
        help="where the customer's words go; `bare` is the ablation, never the product",
    )
    parser.add_argument("--model", default=settings.panel.model)
    parser.add_argument("--workers", type=int, default=_DEFAULT_WORKERS)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the plan and exit; calls nothing and needs no API key",
    )
    args = parser.parse_args()

    part = PARTS[args.part]
    if args.part == "screen":
        # Counted from what `screen_contexts` actually skips, not from an
        # assumption that exactly one context has empty words.
        calls = sum(bool(c.words) for c in part.contexts) * args.replicates
        print(f"{calls} screening calls on {settings.screening_model}.")
    else:
        cells = plan_cells(
            contexts=part.contexts,
            pairs=part.pairs,
            replicates=args.replicates,
            rendering=args.rendering,
            personas=BASE_PERSONAS[: part.personas],
            nonce=f"<<{secrets.token_hex(8)}>>",
        )
        print(
            f"{len(cells)} votes on {args.model}: {len(part.contexts)} context(s), "
            f"{part.personas} persona(s), {len(part.pairs)} pair(s), "
            f"{args.rendering}, {args.workers} worker(s)."
        )
    if args.dry_run:
        return
    if settings.openrouter_api_key is None:
        raise SystemExit("openrouter_api_key is not set; cannot run the panel.")
    key = settings.openrouter_api_key.get_secret_value()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.part == "screen":
        screener = OpenRouterScreener(
            api_key=key,
            base_url=settings.openrouter_base_url,
            provider=settings.model_provider,
            model=settings.screening_model,
        )
        # Appended as each verdict lands, for the same salvage reason: the
        # screener is built with no retries, so one 429 late in the run would
        # otherwise discard every verdict before it.
        flagged = 0
        with args.out.open("w") as sink:
            for row in screen_contexts(
                screener, part.contexts, replicates=args.replicates
            ):
                sink.write(json.dumps(row) + "\n")
                sink.flush()
                flagged += bool(row["flagged"])
        print(f"{flagged} flagged.")
        return

    transport = {
        "api_key": key,
        "base_url": settings.openrouter_base_url,
        "provider": settings.model_provider,
        "model": args.model,
        "question": DEFAULT_FRAMING.question,
    }
    if args.rendering == "human":
        # One adapter per context: the words are bound at construction, the way
        # the question is, because one panel asks one thing of everybody.
        llms: dict[str, PanelLLM] = {
            context.id: (
                HumanTurnPanelLLM(enacted=context.words, **transport)
                if context.words
                else OpenRouterPanelLLM(**transport)
            )
            for context in part.contexts
        }
    else:
        shared = OpenRouterPanelLLM(**transport)
        llms = {context.id: shared for context in part.contexts}
    landed: list[VoteRow] = []
    try:
        rows = collect_rows(llms=llms, cells=cells, workers=args.workers, done=landed)
    except Exception:
        # Salvage before re-raising: these votes are paid for and do not
        # reproduce, so losing them to an unrelated failure costs real money.
        write_rows(landed, args.out)
        print(f"Failed after {len(landed)} votes; wrote them to {args.out}.")
        raise
    write_rows(rows, args.out)
    print(f"Wrote {len(rows)} rows.")


if __name__ == "__main__":
    main()
