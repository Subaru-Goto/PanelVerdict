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
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from app.bigfive import bigfive_from_levels
from app.config import settings
from app.llm import OpenRouterPanelLLM
from app.panel import render_persona_prompt
from app.schemas import Persona, TraitLevel
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


def plan_cells(
    *,
    contexts: tuple[EnactedContext, ...],
    pairs: tuple[HeadlinePair, ...],
    replicates: int,
    fenced: bool,
    personas: tuple[Persona, ...] = BASE_PERSONAS,
    nonce: str = "<<NONCE>>",
) -> list[Cell]:
    """Enumerate every (context × persona × pair × replicate × order) cell.

    Rectangular by construction, because 014's flip rate pairs a vote in one arm
    with the same cell in another and refuses to run on an unmatched design.

    `trait` and `level` are labels here rather than manipulations: the analysis
    matches on `trait`, so it stays constant across arms or no two arms would
    ever line up. `level` carries the context's role, which is what makes the
    report readable.
    """
    cells: list[Cell] = []
    for context in contexts:
        for persona in personas:
            prompt = render_enacted(
                render_persona_prompt(persona),
                context.words,
                nonce=nonce,
                fenced=fenced,
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
                                level=context.role,
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
    *, llm: PanelLLM, cells: list[Cell], workers: int = 1
) -> list[VoteRow]:
    """Vote on every planned cell, in plan order whatever finished first."""
    if workers == 1:
        return [vote_cell(llm, cell) for cell in cells]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda cell: vote_cell(llm, cell), cells))


def screen_contexts(
    screener: Screener, contexts: tuple[EnactedContext, ...], *, replicates: int = 1
) -> list[Mapping[str, object]]:
    """Ask the shipped screener about each context, before any panel sees it.

    An attack the screener refuses never reaches a vote prompt, so this decides
    which rows in the attack run are measuring a live threat and which are
    measuring a defence-in-depth that never has to hold.

    Replicated, because the screener is a model at default temperature: asked
    once, a coin-flip screener and a reliable one produce the same file.
    """
    rows = []
    for context in contexts:
        if not context.words:
            continue
        for replicate in range(replicates):
            verdict = screener.screen(context.words)
            rows.append(
                {
                    "id": context.id,
                    "role": context.role,
                    "replicate": replicate,
                    "words": context.words,
                    "flagged": verdict.flagged,
                    "reason": verdict.reason,
                }
            )
    return rows


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
        "--bare",
        action="store_true",
        help="splice the words in unfenced — the ablation, never the product",
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
        calls = (len(part.contexts) - 1) * args.replicates
        print(f"{calls} screening calls on {settings.screening_model}.")
    else:
        cells = plan_cells(
            contexts=part.contexts,
            pairs=part.pairs,
            replicates=args.replicates,
            fenced=not args.bare,
            personas=BASE_PERSONAS[: part.personas],
            nonce=f"<<{secrets.token_hex(8)}>>",
        )
        print(
            f"{len(cells)} votes on {args.model}: {len(part.contexts)} context(s), "
            f"{part.personas} persona(s), {len(part.pairs)} pair(s), "
            f"{'bare' if args.bare else 'fenced'}, {args.workers} worker(s)."
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
        rows = screen_contexts(screener, part.contexts, replicates=args.replicates)
        args.out.write_text("".join(json.dumps(row) + "\n" for row in rows))
        flagged = sum(bool(row["flagged"]) for row in rows)
        print(f"Wrote {len(rows)} rows. {flagged} flagged.")
        return

    llm = OpenRouterPanelLLM(
        api_key=key,
        base_url=settings.openrouter_base_url,
        provider=settings.model_provider,
        model=args.model,
        question=DEFAULT_FRAMING.question,
    )
    rows = collect_rows(llm=llm, cells=cells, workers=args.workers)
    write_rows(rows, args.out)
    print(f"Wrote {len(rows)} rows.")


if __name__ == "__main__":
    main()
