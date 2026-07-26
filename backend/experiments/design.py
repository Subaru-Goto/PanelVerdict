"""The manipulation check's fixed design (014): stimuli, arms, and one vote's shape.

Imported by both halves so neither depends on the other — collection pulls in the
OpenRouter client and settings, and analysis must stay free of both.
"""

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, get_args

from app.schemas import BigFive

Arm = Literal["demographics", "traits_3", "traits_5"]
ARMS: tuple[Arm, ...] = get_args(Arm)

Choice = Literal["predicted_high", "predicted_low"]
HIGH: Choice = "predicted_high"
LOW: Choice = "predicted_low"

TRAITS: tuple[str, ...] = tuple(BigFive.model_fields)

# Both presentation orders, run for every persona in every cell. Panel-level
# counterbalancing (`collect_panel_votes`, which alternates on index parity) is
# the wrong policy here: a five-level sweep is odd-sized, so it would show three
# personas one order and two the other, and — worse — the imbalance is locked to
# the trait level, since VERY_LOW is always index 0. A position-biased model would
# then manufacture a gradient that looks exactly like the effect under test.
ORDERS: tuple[tuple[Choice, Choice], ...] = ((HIGH, LOW), (LOW, HIGH))


@dataclass(frozen=True)
class HeadlinePair:
    """Two headlines and the direction predicted for `trait`, recorded up front.

    `trait=None` marks the positive control, where every persona is predicted to
    pick `predicted_high` — a model that is not reading the options makes every
    other number in the run meaningless.

    The trait-to-copy mapping is an authored hypothesis, not a sourced one, so a
    null result reads two ways: personas do not steer votes, or these pairs do not
    load on the trait.
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

CONTROL_PAIR: str = next(pair.id for pair in PAIRS if pair.trait is None)


def loaded_pair_id(trait: str) -> str:
    """The pair authored to load on `trait`, resolved rather than assumed equal to
    the trait name, so renaming a pair cannot silently empty a gradient."""
    return next(pair.id for pair in PAIRS if pair.trait == trait)


@dataclass(frozen=True)
class VoteRow:
    """One vote, tagged with the cell that produced it.

    `order` survives to the row so position bias stays separable from the trait
    effect, and measurable in its own right (002 asks the same of the same data).
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


def write_rows(rows: list[VoteRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(asdict(row)) + "\n" for row in rows))


def read_rows(path: Path) -> list[VoteRow]:
    return [
        VoteRow(**json.loads(line)) for line in path.read_text().splitlines() if line
    ]
