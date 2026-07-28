"""Simulate 010d's stopping rule before it spends money: error rates and savings.

No model calls and no network — binomial paths through the *production* decision
function. The rule is evaluated via a lookup table built from `stopping_decision`
itself, so what is simulated is exactly what ships; a reimplementation here could
quietly diverge and validate nothing.

The question this answers: checking the posterior at every chunk boundary is
sequential peeking, which inflates the chance of stopping on a lucky streak. 009
paid for that with `_CONFIRMATIONS = 3`, simulated at the ±7 band. Rule B replaces
the labels, so it owes its own reading: how often does it call a decisive on a
truly tied pair, how often the wrong direction on a real lead, and how many votes
does it save — against the single-look-at-cap baseline, which carries the same
posterior and the same bar without any peeking.
"""

import argparse
from dataclasses import dataclass

import numpy as np

from app.config import PROFILES
from app.verdict import StopReason, stopping_decision
from app.vote import VOTE_CONCURRENCY

# Imported, not restated: a simulation that hard-coded these would keep validating
# a rule nobody runs after either number moves.
CHUNK = VOTE_CONCURRENCY
CAP = PROFILES["prod"].size

# The truths worth measuring, not a grid for its own sake: dead even (the tie stop
# must fire, decisive must not), the band edge (the hardest case, where "worth
# acting on" is a coin flip by construction), just outside, and two clear leads.
TRUE_SHARES = (0.50, 0.55, 0.57, 0.60, 0.65, 0.70)


@dataclass(frozen=True)
class RuleReading:
    """What one (true share, confirmations) cell measured."""

    true_share: float
    confirmations: int
    stopped_early: float
    mean_votes: float
    decided_decisive: float
    decided_tie: float
    wrong_direction: float
    single_look_decisive: float


def decision_table(
    boundaries: np.ndarray, *, credible_mass: float = 0.95
) -> dict[int, np.ndarray]:
    """`stopping_decision` precomputed for every reachable (votes-for-B, n).

    Coded 0 = continue, 1 = decisive-for-B, 2 = decisive-for-A, 3 = practical tie.
    Direction matters only for the wrong-direction count; the rule itself is blind
    to it.
    """
    coded: dict[StopReason | None, int] = {None: 0, "practical_tie": 3}
    table: dict[int, np.ndarray] = {}
    for n in boundaries:
        row = np.zeros(n + 1, dtype=np.int8)
        for k in range(n + 1):
            reason = stopping_decision(
                preferring_b=k, total=n, credible_mass=credible_mass
            )
            if reason == "decisive":
                row[k] = 1 if k * 2 > n else 2
            else:
                row[k] = coded[reason]
        table[int(n)] = row
    return table


def simulate(
    *,
    true_share: float,
    confirmations: int,
    runs: int,
    table: dict[int, np.ndarray],
    rng: np.random.Generator,
) -> RuleReading:
    """Walk `runs` panels through the chunked rule at one true preference share.

    `confirmations` is how many consecutive boundaries must agree (reason and
    direction) before the run stops; 1 means the first crossing ends it.
    """
    boundaries = np.arange(CHUNK, CAP + 1, CHUNK)
    votes_for_b = np.zeros(runs, dtype=np.int64)
    stopped_at = np.zeros(runs, dtype=np.int64)  # 0 = still running
    stop_code = np.zeros(runs, dtype=np.int8)
    streak = np.zeros(runs, dtype=np.int8)
    streak_code = np.zeros(runs, dtype=np.int8)

    # Every run accumulates to the cap, stopped or not. The stop bookkeeping reads
    # the same cumulative counts (paths are identical up to the stop), and the
    # single-look baseline needs the full-panel count for every run — freezing
    # stopped runs and indexing the cap row with their partial counts silently
    # replays the sequential stops into the baseline, which is the bug that made
    # peeking look free in this table's first version.
    for n in boundaries:
        votes_for_b += rng.binomial(CHUNK, true_share, runs)
        running = stopped_at == 0
        code = table[int(n)][votes_for_b]
        same = (code == streak_code) & (code != 0)
        streak = np.where(same, streak + 1, np.where(code != 0, 1, 0))
        streak_code = np.where(code != 0, code, 0).astype(np.int8)
        firing = running & (streak >= confirmations) & (code != 0)
        stopped_at[firing] = n
        stop_code[firing] = code[firing]

    early = stopped_at < CAP
    stopped_at[stopped_at == 0] = CAP
    final_code = table[CAP][votes_for_b]
    return RuleReading(
        true_share=true_share,
        confirmations=confirmations,
        stopped_early=float((early & (stop_code != 0)).mean()),
        mean_votes=float(stopped_at.mean()),
        decided_decisive=float(((stop_code == 1) | (stop_code == 2)).mean()),
        decided_tie=float((stop_code == 3).mean()),
        wrong_direction=float(
            ((stop_code == 2) if true_share > 0.5 else (stop_code == 1)).mean()
            if true_share != 0.5
            else ((stop_code == 1) | (stop_code == 2)).mean()
        ),
        single_look_decisive=float(((final_code == 1) | (final_code == 2)).mean()),
    )


def report(readings: list[RuleReading]) -> str:
    lines = [
        "true_p  conf  stop%   E[votes]  decisive%  tie%   wrongdir%  single-look%",
    ]
    for r in readings:
        lines.append(
            f"{r.true_share:.2f}    {r.confirmations}    "
            f"{r.stopped_early:6.3f}  {r.mean_votes:7.1f}  "
            f"{r.decided_decisive:8.3f}  {r.decided_tie:5.3f}  "
            f"{r.wrong_direction:8.3f}  {r.single_look_decisive:10.3f}"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=20_000)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)
    table = decision_table(np.arange(CHUNK, CAP + 1, CHUNK))
    readings = [
        simulate(true_share=p, confirmations=c, runs=args.runs, table=table, rng=rng)
        for c in (1, 2, 3)
        for p in TRUE_SHARES
    ]
    print(report(readings))


if __name__ == "__main__":
    main()
