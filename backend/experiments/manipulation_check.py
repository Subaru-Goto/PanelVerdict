"""Targeting manipulation check (014): does a persona attribute move a vote?

Constructed personas, not the pool. Every field is held fixed except one trait,
which is swept through all five levels — that is what makes the result causal
rather than correlational, and it is why this needs no database and no seeding.

The sweep *is* `docs/project-idea.md`'s target-vs-control-vs-opposite design,
generalized: MEDIUM is the control group, VERY_HIGH the target, VERY_LOW the
opposite segment, and the two levels between them turn a three-point comparison
into a gradient that can be checked for monotonicity.

Collection is separated from analysis (`experiments/analysis.py`) because these
votes cost money and do not reproduce: the rows go to disk once and every later
question is asked of the file.
"""

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, get_args

from app.bigfive import bigfive_from_levels, bucketize
from app.config import settings
from app.llm import OpenRouterPanelLLM
from app.panel import render_demographics_prompt, render_persona_prompt
from app.schemas import BigFive, Persona, TraitLevel
from app.vote import PanelLLM, resolve_choice

Arm = Literal["demographics", "traits_3", "traits_5"]
ARMS: tuple[Arm, ...] = get_args(Arm)

TRAITS: tuple[str, ...] = tuple(BigFive.model_fields)

# One neutral person, so the swept trait is the only thing that varies and the
# baseline is not itself an unusual persona. Mid-quintile, mid-education, an age
# near the middle of the sampled range.
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


@dataclass(frozen=True)
class HeadlinePair:
    """Two headlines and the prediction under test.

    `predicted_high` is the option a persona at the *high* end of `trait` is
    predicted to prefer. `trait=None` marks the positive control, where the
    prediction is that every persona picks `predicted_high` regardless — a
    manipulation check on the manipulation check, since a model that is not
    reading the options makes every other number in the run meaningless.

    The trait-to-copy mapping is an authored hypothesis, not a sourced one:
    `docs/research/persona-attributes-grounding.md` documents copy levers only
    for the deferred attributes (NFC → verbal complexity, CSII → social proof),
    not for the Big Five domains. A null result therefore has two readings —
    personas do not steer votes, or these pairs do not load on the trait — which
    is exactly why the control pair and the direction predictions are recorded up
    front rather than reasoned about afterwards.
    """

    id: str
    trait: str | None
    predicted_high: str
    predicted_low: str


PAIRS: tuple[HeadlinePair, ...] = (
    HeadlinePair(
        id="openness",
        trait="openness",
        predicted_high="Taste the flavour nobody has tried yet",
        predicted_low="The classic recipe, unchanged since 1954",
    ),
    HeadlinePair(
        id="conscientiousness",
        trait="conscientiousness",
        predicted_high="Plan every detail months ahead, down to the last stop",
        predicted_low="Book tonight, leave tomorrow, figure out the rest later",
    ),
    HeadlinePair(
        id="extraversion",
        trait="extraversion",
        predicted_high="Join hundreds of people at the launch party",
        predicted_low="Enjoy it on your own, somewhere quiet",
    ),
    HeadlinePair(
        id="agreeableness",
        trait="agreeableness",
        predicted_high="Loved by a community that looks after its own",
        predicted_low="Read the independent lab results and judge for yourself",
    ),
    HeadlinePair(
        id="neuroticism",
        trait="neuroticism",
        predicted_high="Protect what matters before something goes wrong",
        predicted_low="Make the most of whatever comes next",
    ),
    HeadlinePair(
        id="control",
        trait=None,
        predicted_high="Free delivery on every order",
        predicted_low="A $14.99 handling fee applies to every order",
    ),
)


# Both presentation orders, run for every persona in every cell. Panel-level
# counterbalancing (`collect_panel_votes`, which alternates on index parity) is
# the wrong policy here: a five-level sweep is odd-sized, so it would show three
# personas one order and two the other, and — worse — the imbalance is locked to
# the trait level, since VERY_LOW is always index 0. A position-biased model would
# then manufacture a gradient that looks exactly like the effect under test.
_ORDERS: tuple[tuple[str, str], ...] = (
    ("predicted_high", "predicted_low"),
    ("predicted_low", "predicted_high"),
)


@dataclass(frozen=True)
class VoteRow:
    """One vote, tagged with the cell that produced it.

    `order` is kept rather than aggregated away so position bias stays separable
    from the trait effect, and measurable in its own right (002's position-bias
    regression asks the same question of the same data).
    """

    arm: str
    trait: str
    level: str
    persona_id: str
    pair_id: str
    replicate: int
    order: str
    chosen: str
    reason: str


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
    """Re-render the sampled levels with the extremes folded onto their neighbours.

    Collapsing *levels* rather than restoring the pre-006j phrase table is what
    isolates granularity: both trait arms read from the same 25 phrases, so the
    only difference between them is whether an extreme draw is allowed to reach
    its extreme phrase.
    """
    levels = {trait: bucketize(score) for trait, score in big_five}
    return bigfive_from_levels(
        **{trait: _COLLAPSED.get(level, level) for trait, level in levels.items()}
    )


def render_arm(persona: Persona, arm: Arm) -> str:
    """Render the persona at the fidelity this arm allows."""
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
) -> list[VoteRow]:
    """Run every (arm × swept level × pair × replicate) cell and tag each vote.

    Replicates re-run an identical prompt, which is what makes the noise floor
    measurable — the panel model runs at default temperature, so a persona can
    flip with no manipulation at all, and every effect size downstream is read
    against that.
    """
    rows: list[VoteRow] = []
    for trait in traits:
        for persona in sweep_personas(trait):
            level = bucketize(getattr(persona.big_five, trait))
            for arm in ARMS:
                prompt = render_arm(persona, arm)
                for pair in PAIRS:
                    options = {
                        "predicted_high": pair.predicted_high,
                        "predicted_low": pair.predicted_low,
                    }
                    for replicate in range(replicates):
                        for order in _ORDERS:
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


def write_rows(rows: list[VoteRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(asdict(row)) + "\n" for row in rows))


def read_rows(path: Path) -> list[VoteRow]:
    return [
        VoteRow(**json.loads(line)) for line in path.read_text().splitlines() if line
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--traits", default=",".join(TRAITS))
    parser.add_argument(
        "--replicates",
        type=int,
        default=5,
        help="identical re-runs per cell; the noise floor is read off these",
    )
    parser.add_argument("--model", default=settings.panel_model)
    parser.add_argument("--out", type=Path, default=Path("experiments/out/votes.jsonl"))
    args = parser.parse_args()

    traits = [trait.strip() for trait in args.traits.split(",")]
    calls = (
        len(ARMS)
        * len(traits)
        * len(TraitLevel)
        * len(PAIRS)
        * args.replicates
        * len(_ORDERS)
    )
    if settings.openrouter_api_key is None:
        raise SystemExit("openrouter_api_key is not set; cannot run the panel.")

    print(f"{calls} votes over {len(traits)} trait(s) on {args.model}.")
    llm = OpenRouterPanelLLM(
        api_key=settings.openrouter_api_key.get_secret_value(),
        base_url=settings.openrouter_base_url,
        model=args.model,
    )
    rows = collect_rows(llm=llm, traits=traits, replicates=args.replicates)
    write_rows(rows, args.out)
    print(
        f"Wrote {len(rows)} rows to {args.out}. Analyse: python -m experiments.analysis {args.out}"
    )


if __name__ == "__main__":
    main()
