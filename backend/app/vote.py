import random
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Literal, Protocol

from app.panel import render_persona_prompt
from app.schemas import PanelVoteOutput, Persona, VoteRecord

# A cap on requests in flight, not a barrier between groups of 25: a group that waits
# for its slowest member leaves the other workers idle, and a reasoning model's latency
# varies enough for that to cost real time. 25 is 008's figure.
VOTE_CONCURRENCY = 25

# Fixed by default, so one test pairs the same panelists with the same positions run
# after run. Separate from the panel's own seed because they answer different questions
# — who votes, versus which order each of them sees.
ORDER_SEED = 0


class PanelLLM(Protocol):
    def vote(
        self, *, system_prompt: str, option_1: str, option_2: str
    ) -> PanelVoteOutput: ...


def presentation_orders(
    variant_ids: tuple[str, str], count: int, *, seed: int
) -> list[list[str]]:
    """One presentation order per panelist: an exact 50/50 split, then shuffled.

    Both halves are load-bearing and they fix different things.

    The split is exact because the model picks the first-shown option 0.66 of the time
    (014), so a surplus of one order is a bias on the top line rather than noise that
    averages out. An odd panel is off by one, which is as close as whole votes get.

    The shuffle is because assigning by index parity — balanced as it is — ties
    who-sees-which-order to however the panel arrived, and the caller chooses that:
    `load_pool` returns id order, which groups by country. Nothing in the pipeline
    guarantees the panel is not sorted by something that matters.

    Seeded, because `presentation_order` is stored per vote and a re-run of one test
    has to pair the same panelist with the same position to be the same test.
    """
    forward, reverse = list(variant_ids), list(reversed(variant_ids))
    first_half = count // 2 + count % 2
    orders = [forward] * first_half + [reverse] * (count - first_half)
    random.Random(seed).shuffle(orders)
    return orders


def resolve_choice(
    chosen: Literal["option_1", "option_2"], presentation_order: list[str]
) -> str:
    """Map a positional pick back to the variant id it referred to.

    The model votes by position (option_1/option_2, blind to identity);
    presentation_order holds the variant_ids in the order shown. So option_1
    -> the variant shown first, option_2 -> the variant shown second.
    """
    return presentation_order[0] if chosen == "option_1" else presentation_order[1]


@dataclass(frozen=True)
class VoteFailure:
    """One panelist whose vote never arrived, and what stopped it."""

    persona_id: str
    error: str


@dataclass(frozen=True)
class PanelVotes:
    """What a panel returned: the votes cast, and who did not manage to cast one.

    The two travel together because a verdict computed from `records` alone would
    silently be a verdict on a smaller panel than was asked for. Reporting the
    shortfall rather than raising is the same division as retrieval's: the mechanism
    says what happened, and the caller decides whether a thinner panel still deserves
    a verdict.
    """

    records: list[VoteRecord]
    failures: tuple[VoteFailure, ...]


def _cast_vote(
    persona: Persona,
    presentation_order: list[str],
    *,
    test_id: str,
    variants: dict[str, str],
    llm: PanelLLM,
) -> VoteRecord:
    """One panelist's vote, identity re-attached. Runs on a worker thread."""
    first_id, second_id = presentation_order
    output = llm.vote(
        system_prompt=render_persona_prompt(persona),
        option_1=variants[first_id],
        option_2=variants[second_id],
    )
    return VoteRecord(
        persona_id=persona.id,
        test_id=test_id,
        chosen_variant_id=resolve_choice(output.chosen, presentation_order),
        presentation_order=presentation_order,
        reason=output.reason,
    )


def collect_panel_votes(
    *,
    test_id: str,
    variants: dict[str, str],
    panel: list[Persona],
    llm: PanelLLM,
    seed: int = ORDER_SEED,
    concurrency: int = VOTE_CONCURRENCY,
) -> PanelVotes:
    """Cast every panelist's vote concurrently, and report the ones that failed.

    Each panelist sees the two variants in one of two orders, drawn from a balanced
    shuffled assignment, votes positionally (blind to which variant is which), and the
    position is resolved back to a variant id.

    A vote that fails after the client's own retries costs that panelist and no other:
    the remaining votes still stand, and the panel comes back short with the reason
    attached. Records are ordered by the panel, never by which answers arrived first,
    so two runs of one test are comparable line by line.
    """
    if len(variants) != 2:
        raise ValueError(
            f"collect_panel_votes requires exactly 2 variants, got {len(variants)}"
        )
    if concurrency < 1:
        raise ValueError(f"a panel needs at least one worker, got {concurrency}")

    first_variant, second_variant = variants
    orders = presentation_orders((first_variant, second_variant), len(panel), seed=seed)

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures: list[Future[VoteRecord]] = [
            pool.submit(
                _cast_vote,
                persona,
                order,
                test_id=test_id,
                variants=variants,
                llm=llm,
            )
            for persona, order in zip(panel, orders)
        ]

    records: list[VoteRecord] = []
    failures: list[VoteFailure] = []
    for persona, future in zip(panel, futures):
        error = future.exception()
        if error is None:
            records.append(future.result())
        else:
            failures.append(
                VoteFailure(
                    persona_id=persona.id,
                    error=f"{type(error).__name__}: {error}",
                )
            )
    return PanelVotes(records=records, failures=tuple(failures))
