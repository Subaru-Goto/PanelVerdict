"""Read the enacted-context check's collected votes (095). Pure — no network, no DB.

Separated from collection for 014's reason: the votes cost money and do not
reproduce, so every question after the run is asked of the file.

Nothing here decides whether enactment passed. It produces the numbers the
write-up weighs together, and each is uninterpretable alone:

- `control_share` — did the model read the options at all,
- `noise_floor` — how often an identical prompt flips, the scale every effect is
  measured against,
- `lift` — the effect: a context's share on the pair it was predicted to move,
  minus the same pair with no context,
- `off_target` — the same context on pairs it was *not* predicted to move, which
  is what separates enactment from generic compliance,
- `position_rate` — per arm, and the one that exposes a hijack: an attack turns a
  vote into an order effect, which a share alone cannot distinguish from taste.
- `flip_rate` — 014's headline measure, borrowed unchanged: the share of matched
  votes that differ between an arm and the baseline.
"""

import argparse
import math
from dataclasses import dataclass
from pathlib import Path

from experiments.analysis import control_share, flip_rate, noise_floor
from experiments.design import HIGH, VoteRow, read_rows
from experiments.enacted_design import BASELINE, CONTEXTS, PAIRS, EnactedContext


def _share_high(rows: list[VoteRow]) -> float:
    return sum(row.chosen == HIGH for row in rows) / len(rows) if rows else 0.0


def _select(rows: list[VoteRow], *, arm: str, pair_id: str) -> list[VoteRow]:
    return [row for row in rows if row.arm == arm and row.pair_id == pair_id]


@dataclass(frozen=True)
class Lift:
    """One context measured on one pair, against the same pair with no context.

    `z` divides the lift by its standard error under the null that both arms
    share one rate, pooled across them. It treats votes as independent Bernoulli
    draws — the assumption to remember when reading it, since replicates are
    independent samples from the model, not independent people.
    """

    context: str
    pair_id: str
    baseline_share: float
    context_share: float
    lift: float
    votes_per_arm: int
    z: float


def lift(rows: list[VoteRow], *, context: str, pair_id: str) -> Lift:
    """How far a context moved one pair off its no-context share.

    Against the baseline arm, never against 0.5: these pairs are authored to have
    a direction, so a lopsided split with no context at all is expected and is
    not evidence that the words did anything.
    """
    base = _select(rows, arm=BASELINE.id, pair_id=pair_id)
    armed = _select(rows, arm=context, pair_id=pair_id)
    if not base or not armed:
        raise ValueError(f"no votes for {context!r} or the baseline on {pair_id!r}")
    base_share, arm_share = _share_high(base), _share_high(armed)
    pooled = _share_high(base + armed)
    n = min(len(base), len(armed))
    se = math.sqrt(2 * pooled * (1 - pooled) / n)
    return Lift(
        context=context,
        pair_id=pair_id,
        baseline_share=base_share,
        context_share=arm_share,
        lift=arm_share - base_share,
        votes_per_arm=n,
        z=(arm_share - base_share) / se if se else 0.0,
    )


def off_target(rows: list[VoteRow], *, context: EnactedContext) -> list[Lift]:
    """The same context on every pair it was *not* predicted to move.

    A context that moves everything has not enacted a reader, it has made the
    model agreeable — and that would show as a lift on the pair we predicted and
    equal lifts everywhere else, which only this comparison can see.
    """
    return [
        lift(rows, context=context.id, pair_id=pair.id)
        for pair in PAIRS
        if pair.id != context.loads_on
    ]


def position_rate(rows: list[VoteRow], *, arm: str) -> float:
    """Share of an arm's votes going to whichever option was shown first.

    Both orders are run for every cell, so an honest preference sits near this
    run's baseline rate and an option-locking attack sits at 1.0. This is the
    measure that separates "the words changed a taste" from "the words took the
    task over".
    """
    selected = [row for row in rows if row.arm == arm]
    if not selected:
        return 0.0
    return sum(row.chosen == row.order for row in selected) / len(selected)


def _arms(rows: list[VoteRow]) -> list[str]:
    present = {row.arm for row in rows}
    return [context.id for context in CONTEXTS if context.id in present]


def format_report(rows: list[VoteRow]) -> str:
    lines = [
        f"{len(rows)} votes, {len(_arms(rows))} arm(s).",
        f"noise floor (identical prompt re-run): {noise_floor(rows):.3f}",
        "",
        "arm                  n   control  first-position",
    ]
    for arm in _arms(rows):
        n = sum(row.arm == arm for row in rows)
        lines.append(
            f"{arm:<20} {n:>3}   {control_share(rows, arm=arm):>6.2f}   "
            f"{position_rate(rows, arm=arm):>13.2f}"
        )

    lines += [
        "",
        # Printed rather than left to be computed by hand: the write-up quotes
        # this number, and a figure no committed command produces cannot be
        # checked by the next reader.
        "paired flip rate vs the no-context arm, pooling every non-comprehension",
        "pair — so it counts a context changing the panel at all, in either",
        "direction, not just movement toward the option we predicted.",
        "",
        "context              flip",
    ]
    for arm in _arms(rows):
        if arm == BASELINE.id:
            continue
        rate = flip_rate(rows, dimension="arm", a=BASELINE.id, b=arm)
        lines.append(f"{arm:<20} {rate:>4.3f}")

    predicted = [c for c in CONTEXTS if c.loads_on and c.id in _arms(rows)]
    if predicted:
        lines += [
            "",
            "predicted lift (context on the pair it should move)",
            "context              pair          base    arm    lift      z",
        ]
        for context in predicted:
            result = lift(rows, context=context.id, pair_id=str(context.loads_on))
            lines.append(
                f"{result.context:<20} {result.pair_id:<12} "
                f"{result.baseline_share:>5.2f}  {result.context_share:>5.2f}  "
                f"{result.lift:>+5.2f}  {result.z:>+5.2f}"
            )
        lines += [
            "",
            "off-target lift (same context, pairs it should not move)",
            "context              pair          base    arm    lift      z",
        ]
        for context in predicted:
            for result in off_target(rows, context=context):
                lines.append(
                    f"{result.context:<20} {result.pair_id:<12} "
                    f"{result.baseline_share:>5.2f}  {result.context_share:>5.2f}  "
                    f"{result.lift:>+5.2f}  {result.z:>+5.2f}"
                )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()
    for path in args.paths:
        print(f"\n=== {path}")
        print(format_report(read_rows(path)))


if __name__ == "__main__":
    main()
