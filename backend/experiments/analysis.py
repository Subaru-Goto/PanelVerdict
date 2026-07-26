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

from app.schemas import TraitLevel
from experiments.design import (
    ARMS,
    CONTROL_PAIR,
    HIGH,
    Arm,
    VoteRow,
    loaded_pair_id,
    read_rows,
)

# One prompt, run more than once. Anything that changes the prompt (arm) or the
# stimulus (pair, order) is a different cell, so replicates of a cell differ only
# by the model's own sampling.
_CELL = ("arm", "trait", "persona_id", "pair_id", "order")

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
    arm_a: Arm,
    arm_b: Arm,
    *,
    levels: tuple[str, ...] | None = None,
) -> float:
    """Share of matched votes that differ between two arms.

    Paired on purpose: two arms can report an identical margin with every vote
    flipped, so a difference of aggregate shares would report no effect where the
    effect is total.

    `levels` restricts the comparison, which matters for traits_3 against
    traits_5: those arms render identically unless an extreme was drawn, so
    including the middle three levels dilutes the rate by construction.
    """
    selected = _loaded(rows)
    if levels is not None:
        selected = [row for row in selected if row.level in levels]
    matched = ("trait", "persona_id", "pair_id", "order", "replicate")
    by_arm = {
        arm: {_key(row, matched): row for row in selected if row.arm == arm}
        for arm in (arm_a, arm_b)
    }
    keys_a, keys_b = (set(by_arm[arm]) for arm in (arm_a, arm_b))
    if keys_a != keys_b or not keys_a:
        raise ValueError(
            f"votes for {arm_a!r} and {arm_b!r} do not line up: "
            f"{len(keys_a ^ keys_b)} unmatched cell(s)"
        )
    flips = sum(
        by_arm[arm_a][key].chosen != by_arm[arm_b][key].chosen for key in keys_a
    )
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


def gradient(rows: list[VoteRow], *, trait: str, arm: Arm) -> Gradient:
    """Share choosing the predicted-high option at each level of `trait`.

    `span_z` divides the span by its standard error under the null that every
    level shares one underlying rate, estimated by pooling the two extremes:
    `sqrt(2·p̄(1−p̄)/n)`. It treats votes as independent Bernoulli draws, which is
    the assumption to remember when reading it — replicates of one cell are
    independent samples from the model, not independent people.
    """
    pair_id = loaded_pair_id(trait)
    selected = [
        r for r in rows if r.arm == arm and r.trait == trait and r.pair_id == pair_id
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


def _flip_lines(rows: list[VoteRow], arms: list[str]) -> list[str]:
    lines = []
    for other in arms:
        if other != "demographics" and "demographics" in arms:
            rate = flip_rate(rows, "demographics", other)
            lines.append(f"  demographics -> {other:<12} {rate:.3f}   (all levels)")
    if {"traits_3", "traits_5"} <= set(arms):
        rate = flip_rate(rows, "traits_3", "traits_5", levels=_EXTREMES)
        lines.append(f"  traits_3     -> traits_5     {rate:.3f}   (extremes only)")
    return lines


def format_report(rows: list[VoteRow]) -> str:
    arms = [arm for arm in ARMS if arm in {row.arm for row in rows}]
    lines = [
        "=== Manipulation check (014) ===",
        f"{len(rows)} votes | position bias {position_bias(rows):.2f}",
        "",
        "Per arm — control pair (should be ~1.00) and noise floor (identical re-run):",
        *(
            f"  {arm:<14} control {control_share(rows, arm=arm):.2f}"
            f"   floor {noise_floor([r for r in rows if r.arm == arm]):.3f}"
            for arm in arms
        ),
        "",
        "Flip rate, paired, control pair excluded:",
        *_flip_lines(rows, arms),
        "",
        "Gradients — share choosing the predicted-high option, by level:",
    ]
    header = "".join(f"{level.value:>10}" for level in TraitLevel)
    lines.append(
        f"  {'trait/arm':<26}{header}{'span':>7}{'z':>6}{'tgt':>7}{'opp':>7}  mono"
    )
    for arm in arms:
        for trait in sorted({row.trait for row in rows}):
            result = gradient(rows, trait=trait, arm=arm)
            shares = "".join(f"{share:>10.2f}" for share in result.shares.values())
            lines.append(
                f"  {trait + '/' + arm:<26}{shares}{result.span:>7.2f}"
                f"{result.span_z:>6.2f}{result.target_lift:>7.2f}"
                f"{result.opposite_lift:>7.2f}  {'yes' if result.monotone else 'no'}"
            )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyse collected manipulation-check votes."
    )
    parser.add_argument("path", type=Path)
    print(format_report(read_rows(parser.parse_args().path)))


if __name__ == "__main__":
    main()
