"""Targeting manipulation check (014): does a persona attribute move a vote?

Constructed personas, not the pool. Every field is held fixed except one trait,
which is swept through all five levels — that is what makes the result causal
rather than correlational, and it is why this needs no database and no seeding.

The sweep *is* `docs/project-idea.md`'s target-vs-control-vs-opposite design,
generalized: MEDIUM is the control group, VERY_HIGH the target, VERY_LOW the
opposite segment, and the levels between them turn a three-point comparison into
a gradient that can be checked for monotonicity.

Run it in stages — the noise floor sizes everything after it, so measure it before
paying for the rest:

    python -m experiments.manipulation_check --arms traits_5 --replicates 6 --out out/floor.jsonl
    python -m experiments.analysis out/floor.jsonl
    python -m experiments.manipulation_check --replicates <sized by the floor> --out out/votes.jsonl
"""

import argparse
from pathlib import Path

from app.bigfive import bigfive_from_levels, bucketize
from app.config import settings
from app.llm import OpenRouterPanelLLM
from app.panel import render_demographics_prompt, render_persona_prompt
from app.schemas import BigFive, Persona, TraitLevel
from app.vote import PanelLLM, resolve_choice
from experiments.design import (
    ARMS,
    HIGH,
    LOW,
    ORDERS,
    PAIRS,
    TRAITS,
    Arm,
    HeadlinePair,
    VoteRow,
    write_rows,
)

# One person held constant, so the swept trait is the only thing that varies.
# Mid-quintile and mid-education keep the baseline from being an unusual persona;
# the age and gender are arbitrary, and this check deliberately does not vary
# demographics at all — it asks whether traits move a vote, holding the rest.
_BASE = {
    "country": "US",
    "age": 42,
    "gender": "female",
    "income_quintile": 3,
    "education": "secondary",
}

_COLLAPSED: dict[TraitLevel, TraitLevel] = {
    TraitLevel.VERY_LOW: TraitLevel.LOW,
    TraitLevel.VERY_HIGH: TraitLevel.HIGH,
}


def sweep_personas(trait: str) -> list[Persona]:
    """Five personas differing only in `trait`, one per level, low to high."""
    if trait not in TRAITS:
        raise KeyError(f"{trait!r} is not a Big Five domain; expected one of {TRAITS}")
    return [
        Persona(
            id=f"{trait}-{level.value}",
            **_BASE,
            big_five=bigfive_from_levels(
                **{t: TraitLevel.MEDIUM for t in TRAITS} | {trait: level}
            ),
        )
        for level in TraitLevel
    ]


def _collapse_to_three(big_five: BigFive) -> BigFive:
    """Fold the extreme levels onto their neighbours.

    Collapsing *levels* rather than restoring the pre-006j phrase table is what
    isolates granularity: both trait arms read from the same 25 phrases, so the
    only difference between them is whether an extreme draw reaches its extreme
    phrase.
    """
    levels = {trait: bucketize(score) for trait, score in big_five}
    return bigfive_from_levels(
        **{trait: _COLLAPSED.get(level, level) for trait, level in levels.items()}
    )


def render_arm(persona: Persona, arm: Arm) -> str:
    """Render the persona at the fidelity this arm allows.

    In the `demographics` arm all five sweep personas render identically — the
    swept trait is the only thing that differs and this arm omits it — which is
    why the noise floor is reported per arm rather than pooled.
    """
    if arm == "demographics":
        return render_demographics_prompt(persona)
    if arm == "traits_3":
        return render_persona_prompt(
            persona.model_copy(
                update={"big_five": _collapse_to_three(persona.big_five)}
            )
        )
    return render_persona_prompt(persona)


def collect_rows(
    *,
    llm: PanelLLM,
    traits: list[str],
    replicates: int,
    arms: tuple[Arm, ...] = ARMS,
    pairs: tuple[HeadlinePair, ...] = PAIRS,
) -> list[VoteRow]:
    """Run every (arm × level × pair × replicate × order) cell and tag each vote.

    Replicates re-run an identical prompt, which is what makes the noise floor
    measurable — the panel model runs at default temperature, so a persona can
    flip with no manipulation at all, and every effect size is read against that.
    """
    rows: list[VoteRow] = []
    for trait in traits:
        for persona in sweep_personas(trait):
            level = bucketize(getattr(persona.big_five, trait))
            for arm in arms:
                prompt = render_arm(persona, arm)
                for pair in pairs:
                    options = {HIGH: pair.predicted_high, LOW: pair.predicted_low}
                    for replicate in range(replicates):
                        for order in ORDERS:
                            output = llm.vote(
                                system_prompt=prompt,
                                option_1=options[order[0]],
                                option_2=options[order[1]],
                            )
                            rows.append(
                                VoteRow(
                                    arm=arm,
                                    trait=trait,
                                    level=level.value,
                                    persona_id=persona.id,
                                    pair_id=pair.id,
                                    replicate=replicate,
                                    order=order[0],
                                    chosen=resolve_choice(output.chosen, list(order)),
                                    reason=output.reason,
                                )
                            )
    return rows


def _selected_arms(value: str) -> tuple[Arm, ...]:
    chosen = tuple(name.strip() for name in value.split(","))
    unknown = set(chosen) - set(ARMS)
    if unknown:
        raise argparse.ArgumentTypeError(
            f"unknown arm(s) {sorted(unknown)}; have {ARMS}"
        )
    return tuple(arm for arm in ARMS if arm in chosen)


def _selected_pairs(value: str) -> tuple[HeadlinePair, ...]:
    chosen = tuple(name.strip() for name in value.split(","))
    unknown = set(chosen) - {pair.id for pair in PAIRS}
    if unknown:
        raise argparse.ArgumentTypeError(f"unknown pair(s) {sorted(unknown)}")
    return tuple(pair for pair in PAIRS if pair.id in chosen)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--replicates",
        type=int,
        required=True,
        help="identical re-runs per cell; size this from a noise-floor run first",
    )
    parser.add_argument("--traits", default=",".join(TRAITS))
    parser.add_argument("--arms", type=_selected_arms, default=ARMS)
    parser.add_argument("--pairs", type=_selected_pairs, default=PAIRS)
    parser.add_argument("--model", default=settings.panel_model)
    parser.add_argument("--out", type=Path, default=Path("experiments/out/votes.jsonl"))
    args = parser.parse_args()

    traits = [trait.strip() for trait in args.traits.split(",")]
    calls = (
        len(args.arms)
        * len(traits)
        * len(TraitLevel)
        * len(args.pairs)
        * args.replicates
        * len(ORDERS)
    )
    if settings.openrouter_api_key is None:
        raise SystemExit("openrouter_api_key is not set; cannot run the panel.")

    print(
        f"{calls} votes on {args.model}: {len(args.arms)} arm(s), {len(traits)} trait(s)."
    )
    llm = OpenRouterPanelLLM(
        api_key=settings.openrouter_api_key.get_secret_value(),
        base_url=settings.openrouter_base_url,
        model=args.model,
    )
    rows = collect_rows(
        llm=llm,
        traits=traits,
        replicates=args.replicates,
        arms=args.arms,
        pairs=args.pairs,
    )
    write_rows(rows, args.out)
    print(f"Wrote {len(rows)} rows. Analyse: python -m experiments.analysis {args.out}")


if __name__ == "__main__":
    main()
