"""How often the vote split hands the analyst a finding that is not there.

`splits_by_variant` reads every level of every dimension at one bar — around
forty readings on an untargeted prod panel — and each one is the same posterior
the report's own verdict uses. That is deliberate (041/#139: a subgroup is a
smaller panel and needs no statistics of its own), but it means the block runs
many simultaneous tests, and some will clear the bar with nothing behind them.

No model calls: every vote here is a coin flip, so any `decisive` row the block
reports is by construction spurious. Panels are drawn the way the sampler draws
them — trait levels through the production `bucketize` of standard-normal scores
— so the thin extreme cells are as thin as they really are.

    python -m experiments.split_noise

Writes the table to docs/research/vote-split-noise.md's numbers; the summary it
prints is what that record quotes.
"""

import random
from collections import defaultdict
from typing import get_args

import numpy as np
import tiktoken

from app.bigfive import bucketize
from app.schemas import (
    EducationLevel,
    IncomeBand,
    Locale,
    PanelVote,
    TraitLevel,
    TraitName,
)
from app.splits import levels_of, splits_by_variant
from app.verdict import probability_meaningfully_preferred
from tests.factories import make_panel_vote

REPORTS = 300
PANEL = 200

# Arm 2's planted effect, chosen rather than measured: a deliberately strong,
# monotone age effect, so the flag's cost on a true finding is measurable at all.
# It is not a claim about how real readers behave, and the record says so.
_YOUNGEST_PREFERS_B = 0.30
_AGE_SWING = 0.55
_SWING_FROM = 25
_SWING_TO = 70
# Derived, not listed: the app owns what a voter carries.
_TRAITS = get_args(TraitName)
_INCOME_BANDS = get_args(IncomeBand)


def _coin_flip_panel(seed: int, size: int) -> list[PanelVote]:
    """A panel with no effect in it at all: the choice is independent of the voter."""
    rng = random.Random(seed)
    gen = np.random.default_rng(seed)
    return [
        make_panel_vote(
            f"p{index}",
            chosen=rng.choice(["a", "b"]),
            age=rng.randint(18, 84),
            country=rng.choice(list(Locale)),
            gender=rng.choice(["female", "male"]),
            education=rng.choice(list(EducationLevel)),
            income_band=rng.choice(_INCOME_BANDS),
            traits={
                trait: bucketize(float(gen.standard_normal())) for trait in _TRAITS
            },
        )
        for index in range(size)
    ]


def _age_effect_panel(seed: int, size: int) -> list[PanelVote]:
    """A panel with one real effect: older voters prefer B, no trait effect at all.

    The lift on conscientiousness reproduces what the sampler already builds in
    (`docs/research/persona-seed-data.md`: mu rises with age), so this arm also
    shows the confound the block warns about — a trait split appearing where only
    age was planted.
    """
    rng = random.Random(seed)
    gen = np.random.default_rng(seed)
    votes = []
    for index in range(size):
        age = rng.randint(18, 84)
        lift = (age - 45) / 100
        traits = {
            trait: bucketize(
                float(gen.standard_normal())
                + (lift if trait == "conscientiousness" else 0.0)
            )
            for trait in _TRAITS
        }
        prefers_b = _YOUNGEST_PREFERS_B + _AGE_SWING * min(
            max((age - _SWING_FROM) / (_SWING_TO - _SWING_FROM), 0), 1
        )
        votes.append(
            make_panel_vote(
                f"p{index}",
                chosen="b" if rng.random() < prefers_b else "a",
                age=age,
                country=Locale.US,
                gender=rng.choice(["female", "male"]),
                education=rng.choice(list(EducationLevel)),
                income_band=rng.choice(_INCOME_BANDS),
                traits=traits,
            )
        )
    return votes


def _cells(votes: list[PanelVote]) -> list[tuple[int, int]]:
    tallies: dict[str, dict[str, list[int]]] = defaultdict(
        lambda: defaultdict(lambda: [0, 0])
    )
    for vote in votes:
        for dimension, level in levels_of(vote.voter):
            tallies[dimension][level][0] += vote.chosen_variant_id == "b"
            tallies[dimension][level][1] += 1
    return [
        (preferring_b, total)
        for levels in tallies.values()
        for preferring_b, total in levels.values()
    ]


# The ticket asks for the three-band collapse to be costed, not assumed
# (041/#139: "should be costed against losing the very_high row that a targeting
# question most often asks about"). Folding the extremes inward is the collapse
# it names; `_COLLAPSE` is applied to the drawn level, so the panel is identical
# and only the grouping differs.
_COLLAPSE = {
    TraitLevel.VERY_LOW: TraitLevel.LOW,
    TraitLevel.LOW: TraitLevel.LOW,
    TraitLevel.MEDIUM: TraitLevel.MEDIUM,
    TraitLevel.HIGH: TraitLevel.HIGH,
    TraitLevel.VERY_HIGH: TraitLevel.HIGH,
}


def _collapsed(votes: list[PanelVote]) -> list[PanelVote]:
    """The same votes with each trait read at three bands instead of five."""
    return [
        vote.model_copy(
            update={
                "voter": vote.voter.model_copy(
                    update={
                        "traits": {
                            trait: _COLLAPSE[level]
                            for trait, level in vote.voter.traits.items()
                        }
                    }
                )
            }
        )
        for vote in votes
    ]


def _trait_rows(votes: list[PanelVote]) -> list:
    return [
        row
        for split in splits_by_variant(votes).dimensions
        if split.dimension in _TRAITS
        for row in split.rows
    ]


def _cost_the_collapse() -> None:
    five_noise = three_noise = 0
    five_true = three_true = 0
    extreme_true = 0
    for seed in range(REPORTS):
        flat = _coin_flip_panel(seed, PANEL)
        five_noise += any(row.verdict == "decisive" for row in _trait_rows(flat))
        three_noise += any(
            row.verdict == "decisive" for row in _trait_rows(_collapsed(flat))
        )
        real = _age_effect_panel(seed, PANEL)
        five = [row for row in _trait_rows(real) if row.verdict == "decisive"]
        five_true += len(five)
        extreme_true += sum(1 for row in five if row.level in ("very_low", "very_high"))
        three_true += sum(
            1 for row in _trait_rows(_collapsed(real)) if row.verdict == "decisive"
        )
    print("\ncosting the three-band collapse, trait dimensions only:")
    print(
        f"  noise: a decisive trait row in {five_noise}/{REPORTS} reports at five "
        f"bands, {three_noise}/{REPORTS} at three"
    )
    print(
        f"  effect arm: {five_true} decisive trait rows at five bands, "
        f"{three_true} at three"
    )
    print(
        f"  of the five-band rows, {extreme_true} were very_low/very_high — the "
        f"rows a collapse cannot report at all"
    )


def main() -> None:
    spurious: list[int] = []
    isolated_share: list[tuple[int, int]] = []
    for seed in range(REPORTS):
        votes = _coin_flip_panel(seed, PANEL)
        rows = [
            row for split in splits_by_variant(votes).dimensions for row in split.rows
        ]
        called = [row for row in rows if row.verdict == "decisive"]
        spurious.append(len(called))
        isolated_share.append((sum(1 for row in called if row.isolated), len(called)))

    rows_per_report = len(_cells(_coin_flip_panel(0, PANEL)))
    carried = sum(1 for count in spurious if count)
    flagged = sum(flag for flag, _ in isolated_share)
    total_called = sum(count for _, count in isolated_share)
    print(f"reports={REPORTS} panel={PANEL} rows_per_report={rows_per_report}")
    print(
        f"spurious decisive rows: mean={np.mean(spurious):.2f} "
        f"max={max(spurious)} total={sum(spurious)}"
    )
    print(
        f"reports carrying at least one: {carried}/{REPORTS} "
        f"= {carried / REPORTS * 100:.0f}%"
    )
    print(
        f"of the {total_called} spurious rows, {flagged} were marked isolated "
        f"= {flagged / total_called * 100:.0f}%"
    )

    blob = splits_by_variant(_coin_flip_panel(0, PANEL)).model_dump_json()
    tokens = len(tiktoken.get_encoding("o200k_base").encode(blob))
    print(f"\nblock size: {len(blob)} chars = {tokens} tokens (o200k_base)")

    print("\nfamily-wise rate if the per-cell bar were raised:")
    probs = [
        [
            max(preferred.a, preferred.b)
            for preferred in (
                probability_meaningfully_preferred(preferring_b=b, total=t)
                for b, t in _cells(_coin_flip_panel(seed, PANEL))
            )
        ]
        for seed in range(REPORTS)
    ]
    for bar in (0.95, 0.97, 0.98, 0.99, 0.995, 0.999):
        hit = sum(1 for report in probs if any(p >= bar for p in report))
        print(f"  bar={bar:<6.3f} {hit:3d}/{REPORTS} = {hit / REPORTS * 100:5.1f}%")

    _cost_the_collapse()

    print("\nthe other arm: one real effect (older voters prefer B), same panel size")
    real_called = real_flagged = reports_with_age = 0
    for seed in range(REPORTS):
        splits = splits_by_variant(_age_effect_panel(seed, PANEL))
        age = next(s for s in splits.dimensions if s.dimension == "age_band")
        called = [row for row in age.rows if row.verdict == "decisive"]
        real_called += len(called)
        real_flagged += sum(1 for row in called if row.isolated)
        reports_with_age += bool(called)
    print(
        f"  age_band rows called decisive: {real_called} over {REPORTS} reports; "
        f"{reports_with_age}/{REPORTS} reports found the effect"
    )
    print(
        f"  of those, marked isolated: {real_flagged} "
        f"= {real_flagged / max(real_called, 1) * 100:.0f}%"
    )


if __name__ == "__main__":
    main()
