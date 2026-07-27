"""Read the manipulation check's collected votes (014). Pure — no network, no DB.

Separated from collection because the votes cost money and do not reproduce, so
every question after the run is asked of the file rather than of the model.

Nothing here decides whether the check passed. It produces the numbers the
write-up has to weigh together, and each is uninterpretable alone:

- `control_share` — did the model read the options at all,
- `noise_floor` — how often an identical prompt flips, which is the scale every
  effect below is measured against,
- `position_bias` — could the arrangement rather than the persona explain a split,
- `gradient` — the effect itself: target vs. control vs. opposite segment.

The control pair is excluded from the noise floor and the flip rates. It is built
so that no persona should dispute it, so pooling it would pin those statistics
toward zero and understate both.
"""

import argparse
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, get_args

from app.schemas import TraitLevel
from experiments.design import (
    ARMS,
    CONTROL_PAIR,
    FRAMINGS,
    HIGH,
    PAIRS,
    Arm,
    Role,
    VoteRow,
    loaded_pair_id,
    read_rows,
)

# One prompt, run more than once. Anything that changes the prompt (arm, framing)
# or the stimulus (pair, order) is a different cell, so replicates of a cell differ
# only by the model's own sampling. Leaving `framing` out would group replicates of
# different questions as identical re-runs: the floor would absorb the whole framing
# effect, every flip rate would then sit at the floor, and 015 would report framings
# as interchangeable whatever the model did.
Dimension = Literal["framing", "arm", "trait", "persona_id", "pair_id", "order"]
_CELL: tuple[Dimension, ...] = get_args(Dimension)

_EXTREMES = (TraitLevel.VERY_LOW.value, TraitLevel.VERY_HIGH.value)


def _key(row: VoteRow, fields: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(str(getattr(row, field)) for field in fields)


def _group(
    rows: list[VoteRow], fields: tuple[str, ...]
) -> dict[tuple[str, ...], list[VoteRow]]:
    grouped: dict[tuple[str, ...], list[VoteRow]] = defaultdict(list)
    for row in rows:
        grouped[_key(row, fields)].append(row)
    return grouped


def _share_high(rows: list[VoteRow]) -> float:
    return sum(row.chosen == HIGH for row in rows) / len(rows)


def _loaded(rows: list[VoteRow]) -> list[VoteRow]:
    return [row for row in rows if row.pair_id != CONTROL_PAIR]


def noise_floor(rows: list[VoteRow]) -> float:
    """How often two replicates of the *same* prompt disagree.

    The panel model runs at default temperature, so this is not zero, and it is
    the floor every effect size has to clear. Computed as the mean probability
    that two randomly drawn replicates of a cell differ, which uses every pair
    rather than only consecutive ones; cells run once contribute nothing.
    """
    rates = []
    for cell in _group(_loaded(rows), _CELL).values():
        n = len(cell)
        if n < 2:
            continue
        high = sum(row.chosen == HIGH for row in cell)
        rates.append(2 * high * (n - high) / (n * (n - 1)))
    return sum(rates) / len(rates) if rates else 0.0


def flip_rate(
    rows: list[VoteRow],
    *,
    dimension: Dimension,
    a: str,
    b: str,
    levels: tuple[str, ...] | None = None,
) -> float:
    """Share of matched votes that differ between two values of `dimension`.

    Paired on purpose: two arms can report an identical margin with every vote
    flipped, so a difference of aggregate shares would report no effect where the
    effect is total.

    Votes are matched on every cell field except `dimension`, plus the replicate.
    Deriving that rather than listing it is what lets one function compare arms
    (014) and framings (015), and it forces the caller to name what varies.

    `levels` restricts the comparison, which matters for traits_3 against
    traits_5: those arms render identically unless an extreme was drawn, so
    including the middle three levels dilutes the rate by construction.
    """
    if dimension not in _CELL:
        raise ValueError(f"{dimension!r} is not a cell dimension; have {_CELL}")
    selected = _loaded(rows)
    if levels is not None:
        selected = [row for row in selected if row.level in levels]
    matched = tuple(field for field in _CELL if field != dimension) + ("replicate",)
    sides = {
        value: {
            _key(row, matched): row
            for row in selected
            if getattr(row, dimension) == value
        }
        for value in (a, b)
    }
    keys_a, keys_b = (set(sides[value]) for value in (a, b))
    if keys_a != keys_b or not keys_a:
        raise ValueError(
            f"votes for {a!r} and {b!r} do not line up: "
            f"{len(keys_a ^ keys_b)} unmatched cell(s)"
        )
    flips = sum(sides[a][key].chosen != sides[b][key].chosen for key in keys_a)
    return flips / len(keys_a)


@dataclass(frozen=True)
class Gradient:
    """One trait's sweep in one arm — the target/control/opposite comparison.

    `target_lift` and `opposite_lift` are each extreme minus MEDIUM: the design's
    actual claim is that the target segment diverges *from the control group*, and
    they should carry opposite signs. `span` is the two extremes against each
    other. `monotone` says the five shares never decrease, which is worthless on
    its own — a flat line is monotone — and informative only beside a span.
    """

    trait: str
    arm: str
    shares: dict[str, float]
    votes_per_level: int
    span: float
    target_lift: float
    opposite_lift: float
    monotone: bool
    span_z: float


def gradient(
    rows: list[VoteRow], *, trait: str, arm: Arm, framing: str | None = None
) -> Gradient:
    """Share choosing the predicted-high option at each level of `trait`.

    `span_z` divides the span by its standard error under the null that every
    level shares one underlying rate, estimated by pooling the two extremes:
    `sqrt(2·p̄(1−p̄)/n)`. It treats votes as independent Bernoulli draws, which is
    the assumption to remember when reading it — replicates of one cell are
    independent samples from the model, not independent people.
    """
    pair_id = loaded_pair_id(trait)
    selected = [
        r
        for r in rows
        if r.arm == arm
        and r.trait == trait
        and r.pair_id == pair_id
        and (framing is None or r.framing == framing)
    ]
    by_level = _group(selected, ("level",))
    missing = [level.value for level in TraitLevel if (level.value,) not in by_level]
    if missing:
        raise ValueError(
            f"no votes for {trait!r} in arm {arm!r} at level(s): {missing}"
        )

    shares = {
        level.value: _share_high(by_level[(level.value,)]) for level in TraitLevel
    }
    low, high = _EXTREMES
    span = shares[high] - shares[low]

    pooled = _share_high(by_level[(low,)] + by_level[(high,)])
    n = min(len(by_level[(low,)]), len(by_level[(high,)]))
    se = math.sqrt(2 * pooled * (1 - pooled) / n)

    ordered = list(shares.values())
    return Gradient(
        trait=trait,
        arm=arm,
        shares=shares,
        votes_per_level=n,
        span=span,
        target_lift=shares[high] - shares[TraitLevel.MEDIUM.value],
        opposite_lift=shares[low] - shares[TraitLevel.MEDIUM.value],
        monotone=all(a <= b for a, b in zip(ordered, ordered[1:])),
        span_z=span / se if se else 0.0,
    )


@dataclass(frozen=True)
class LeverResult:
    """One population-level pair's split, against the null of no preference."""

    pair_id: str
    role: Role
    grounding: str | None
    share_high: float
    votes: int
    z: float


def lever_results(
    rows: list[VoteRow], *, framing: str | None = None
) -> list[LeverResult]:
    """Share choosing the lever-carrying variant, for every published pair (015).

    `predicted_high` is always the variant carrying the lever, so a `published`
    pair predicts a share above 0.5 and a `published_null` pair predicts exactly
    0.5. Reading both on one scale is what makes the null usable as a
    false-positive check rather than a separate ritual: a panel that splits hard on
    the null is inventing a preference the field data says humans do not have.

    Unlike a gradient this pools every persona, because the published direction is
    a population-level claim — nothing about it is persona-conditional.
    """
    selected = [row for row in rows if framing is None or row.framing == framing]
    results = []
    for pair in PAIRS:
        if pair.role not in ("published", "published_null"):
            continue
        votes = [row for row in selected if row.pair_id == pair.id]
        if not votes:
            continue
        share = _share_high(votes)
        results.append(
            LeverResult(
                pair_id=pair.id,
                role=pair.role,
                grounding=pair.grounding,
                share_high=share,
                votes=len(votes),
                # Under no preference p = 0.5, whose sd is sqrt(0.25/n). The null is
                # fixed rather than estimated, so nothing degenerates the way a
                # pooled-share denominator can.
                z=(share - 0.5) / math.sqrt(0.25 / len(votes)),
            )
        )
    return results


def control_share(rows: list[VoteRow], *, arm: Arm | None = None) -> float:
    """Share picking the obviously-better option on the control pair.

    Well below 1 means the model is not reading the options, and every other
    number in the run is then noise dressed as a finding. Readable per arm,
    because comprehension could fail in only one of them.
    """
    control = [
        row
        for row in rows
        if row.pair_id == CONTROL_PAIR and (arm is None or row.arm == arm)
    ]
    return _share_high(control) if control else 0.0


def position_bias(rows: list[VoteRow]) -> float:
    """Share picking whichever option was shown first — 0.5 is unbiased."""
    return sum(row.chosen == row.order for row in rows) / len(rows)


def _values(rows: list[VoteRow], field: str, ordered: list[str]) -> list[str]:
    present = {getattr(row, field) for row in rows}
    return [value for value in ordered if value in present]


def _cell_lines(rows: list[VoteRow], arms: list[str], framings: list[str]) -> list[str]:
    lines = []
    for framing in framings:
        for arm in arms:
            cell = [r for r in rows if r.framing == framing and r.arm == arm]
            # 014 ran three arms under one framing and 015 runs one arm under
            # three, so most of this grid is empty whenever both files are read.
            if not cell:
                continue
            lines.append(
                f"  {framing + '/' + arm:<28} control {control_share(cell):.2f}"
                f"   floor {noise_floor(cell):.3f}"
                f"   position {position_bias(cell):.2f}"
            )
    return lines


def _flip_lines(rows: list[VoteRow], arms: list[str], framings: list[str]) -> list[str]:
    """Arms compared within one framing, framings within one arm — never across.

    A flip between two arms that were asked different questions would credit the
    question's effect to the arm, and vice versa.
    """
    lines = []
    for framing in framings:
        within = [row for row in rows if row.framing == framing]
        here = _values(within, "arm", arms)
        for other in here:
            if other != "demographics" and "demographics" in here:
                rate = flip_rate(within, dimension="arm", a="demographics", b=other)
                lines.append(
                    f"  {framing:<11} arm      demographics -> {other:<12}"
                    f" {rate:.3f}  (all levels)"
                )
        if {"traits_3", "traits_5"} <= set(here):
            rate = flip_rate(
                within, dimension="arm", a="traits_3", b="traits_5", levels=_EXTREMES
            )
            lines.append(
                f"  {framing:<11} arm      traits_3     -> traits_5    "
                f" {rate:.3f}  (extremes only)"
            )
    for arm in arms:
        within = [row for row in rows if row.arm == arm]
        baseline, *others = _values(within, "framing", framings)
        for other in others:
            rate = flip_rate(within, dimension="framing", a=baseline, b=other)
            lines.append(
                f"  {arm:<11} framing  {baseline:<12} -> {other:<12} {rate:.3f}"
            )
    return lines


def _gradient_lines(
    rows: list[VoteRow], arms: list[str], framings: list[str], traits: list[str]
) -> list[str]:
    lines = []
    for framing in framings:
        for arm in arms:
            cell = [r for r in rows if r.framing == framing and r.arm == arm]
            if not cell:
                continue
            for trait in traits:
                result = gradient(rows, trait=trait, arm=arm, framing=framing)
                shares = "".join(f"{share:>10.2f}" for share in result.shares.values())
                label = f"{trait}/{arm}/{framing}"
                lines.append(
                    f"  {label:<44}{shares}{result.span:>7.2f}"
                    f"{result.span_z:>6.2f}{result.target_lift:>7.2f}"
                    f"{result.opposite_lift:>7.2f}"
                    f"  {'yes' if result.monotone else 'no'}"
                )
    return lines


def _lever_lines(rows: list[VoteRow], framings: list[str]) -> list[str]:
    lines = [
        f"  {'framing':<12}{'pair':<16}{'share':>7}{'z':>7}{'n':>6}  predicted  source"
    ]
    for framing in framings:
        for result in lever_results(rows, framing=framing):
            predicted = "= 0.50" if result.role == "published_null" else "> 0.50"
            lines.append(
                f"  {framing:<12}{result.pair_id:<16}{result.share_high:>7.2f}"
                f"{result.z:>7.1f}{result.votes:>6}  {predicted}     "
                f"{result.grounding}"
            )
    return lines


def format_report(rows: list[VoteRow]) -> str:
    arms = _values(rows, "arm", list(ARMS))
    framings = _values(rows, "framing", [framing.id for framing in FRAMINGS])
    # A run selects its pairs, so a trait whose pair was not run has no gradient to
    # report — asking for one raises rather than printing an empty row.
    present = {row.pair_id for row in rows}
    traits = [
        trait
        for trait in sorted({row.trait for row in rows})
        if loaded_pair_id(trait) in present
    ]

    lines = [
        "=== Manipulation check (014 / 015) ===",
        f"{len(rows)} votes | position bias {position_bias(rows):.2f} | "
        f"arms: {', '.join(arms)} | framings: {', '.join(framings)}",
        "",
        "Per framing and arm — control pair (~1.00), noise floor, position bias:",
        *_cell_lines(rows, arms, framings),
    ]

    lever_header, *levers = _lever_lines(rows, framings)
    if levers:
        lines += [
            "",
            "Published levers — share choosing the lever-carrying variant:",
            lever_header,
            *levers,
        ]

    lines += [
        "",
        "Flip rate, paired, comprehension pair excluded:",
        *_flip_lines(rows, arms, framings),
    ]

    if traits:
        levels = "".join(f"{level.value:>10}" for level in TraitLevel)
        lines += [
            "",
            "Gradients — share choosing the predicted-high option, by level:",
            f"  {'trait/arm/framing':<44}{levels}{'span':>7}{'z':>6}"
            f"{'tgt':>7}{'opp':>7}  mono",
            *_gradient_lines(rows, arms, framings, traits),
        ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyse collected manipulation-check votes."
    )
    parser.add_argument("path", type=Path)
    print(format_report(read_rows(parser.parse_args().path)))


if __name__ == "__main__":
    main()
