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
# counterbalancing (`collect_panel_votes`, one order per panelist) is still the wrong
# policy here even now that the assignment is shuffled rather than index-parity: a
# five-level sweep is odd-sized, so three personas would see one order and two the
# other, and which levels take the surplus would then vary with the seed. Running
# both orders per persona removes position as a variable instead of balancing it,
# which is what a within-persona comparison needs.
ORDERS: tuple[tuple[Choice, Choice], ...] = ((HIGH, LOW), (LOW, HIGH))


@dataclass(frozen=True)
class Framing:
    """The question a panel is asked (015).

    `question` is duplicated from `app.llm.VOTE_QUESTION` rather than imported:
    this module is the one both halves of the experiment share, and analysis must
    stay free of langchain. A test asserts the baseline framing still equals the
    shipped question, which is what stops the copy becoming a fourth framing.

    The wordings are authored, so a null reads two ways — the verdict is robust to
    framing, or these three are too alike to separate.
    """

    id: str
    question: str


FRAMINGS: tuple[Framing, ...] = (
    Framing(id="preference", question="Which do you prefer?"),
    Framing(id="click", question="Which would you be more likely to click?"),
    Framing(id="attention", question="Which one catches your eye?"),
)

DEFAULT_FRAMING: Framing = FRAMINGS[0]

# What a pair's predicted direction rests on, which is not the same question as
# what it varies. One discriminant rather than a set of flags that can disagree:
#
#   trait          — persona-conditional, authored (014)
#   published      — population-level, a confirmed published effect
#   published_null — population-level, a published *null*; our false-positive check
#   comprehension  — no real choice to make; a model failing it invalidates the run
Role = Literal["trait", "published", "published_null", "comprehension"]


@dataclass(frozen=True)
class HeadlinePair:
    """Two headlines and the direction predicted between them, recorded up front.

    `predicted_high` is always the variant carrying the lever under test, so a
    `published_null` pair predicts a share of 0.5 rather than leaving the
    assignment arbitrary — every population-level pair then reads the same way.

    `grounding` is None exactly where we authored the direction ourselves. The
    trait-to-copy mapping is one such hypothesis, so a null on a trait pair reads
    two ways: personas do not steer votes, or these pairs do not load on the trait.
    """

    id: str
    role: Role
    predicted_high: str
    predicted_low: str
    trait: str | None = None
    grounding: str | None = None


# Gligorić, Lifchits, West & Anderson 2023 (PLOS ONE, doi:10.1371/journal.pone.0281682)
# pre-registered twelve hypotheses and tested them on 24,333 Upworthy A/B pairs. The
# β's are within-experiment associations over naturally-occurring headlines, not
# minimal-pair manipulations, so only the *directions* carry over to a constructed
# pair — never the magnitudes.
_GLIGORIC = "Gligorić et al. 2023"

PAIRS: tuple[HeadlinePair, ...] = (
    HeadlinePair(
        id="openness",
        role="trait",
        trait="openness",
        predicted_high="Taste the flavour nobody has tried yet",
        predicted_low="The classic recipe, unchanged since 1954",
    ),
    HeadlinePair(
        id="conscientiousness",
        role="trait",
        trait="conscientiousness",
        predicted_high="Plan every detail months ahead, down to the last stop",
        predicted_low="Book tonight, leave tomorrow, figure out the rest later",
    ),
    HeadlinePair(
        id="extraversion",
        role="trait",
        trait="extraversion",
        predicted_high="Join hundreds of people at the launch party",
        predicted_low="Enjoy it on your own, somewhere quiet",
    ),
    HeadlinePair(
        id="agreeableness",
        role="trait",
        trait="agreeableness",
        predicted_high="Loved by a community that looks after its own",
        predicted_low="Read the independent lab results and judge for yourself",
    ),
    HeadlinePair(
        id="neuroticism",
        role="trait",
        trait="neuroticism",
        predicted_high="Protect what matters before something goes wrong",
        predicted_low="Make the most of whatever comes next",
    ),
    HeadlinePair(
        id="control",
        role="comprehension",
        predicted_high="Free delivery on every order",
        predicted_low="A $14.99 handling fee applies to every order",
    ),
    # Below: one proposition worded two ways, differing on a single lever. The
    # pairs above are opposed propositions instead, so they cannot answer anything
    # about wording — which is the regime a customer's A/B test lives in.
    HeadlinePair(
        id="pronoun_person",
        role="published",
        predicted_high="I cut my grocery bill in half in one month",
        predicted_low="We cut our grocery bill in half in one month",
        grounding=f"{_GLIGORIC} H6a/H6b (β +0.241 vs −0.149)",
    ),
    HeadlinePair(
        id="person_number",
        role="published",
        predicted_high="She rebuilt her savings in a year",
        predicted_low="They rebuilt their savings in a year",
        grounding=f"{_GLIGORIC} H8a/H8b (β +0.216 vs +0.094)",
    ),
    HeadlinePair(
        id="article",
        role="published",
        predicted_high="A simple change that lowers heating costs",
        predicted_low="The simple change that lowers heating costs",
        grounding=f"{_GLIGORIC} H5a/H5b (β +0.125 vs +0.033 n.s.)",
    ),
    # Second-person pronouns did *not* move real clicks, so the prediction here is
    # 0.5. A panel that splits hard on this is inventing a preference humans do not
    # have — a false-positive detector with a citation, rather than a hand-built one.
    HeadlinePair(
        id="second_person",
        role="published_null",
        predicted_high="Three ways you can lower a heating bill",
        predicted_low="Three ways to lower a heating bill",
        grounding=f"{_GLIGORIC} H7 (β +0.051, hypothesis rejected)",
    ),
)

CONTROL_PAIR: str = next(pair.id for pair in PAIRS if pair.role == "comprehension")


def loaded_pair_id(trait: str) -> str:
    """The pair authored to load on `trait`, resolved rather than assumed equal to
    the trait name, so renaming a pair cannot silently empty a gradient."""
    return next(pair.id for pair in PAIRS if pair.trait == trait)


@dataclass(frozen=True)
class VoteRow:
    """One vote, tagged with the cell that produced it.

    `order` survives to the row so position bias stays separable from the trait
    effect, and measurable in its own right (002 asks the same of the same data).

    `framing` carries a default so 014's collected rows parse unchanged. That is a
    record rather than a backfill: those votes really were cast under the shipped
    question.
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
    framing: str = DEFAULT_FRAMING.id


def write_rows(rows: list[VoteRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(asdict(row)) + "\n" for row in rows))


def read_rows(path: Path) -> list[VoteRow]:
    return [
        VoteRow(**json.loads(line)) for line in path.read_text().splitlines() if line
    ]
