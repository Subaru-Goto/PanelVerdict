import hashlib
import json
import random
from collections.abc import Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Literal, Protocol

from app.panel import render_persona_prompt
from app.schemas import PanelVoteOutput, Persona, VoteRecord

# A cap on requests in flight, not a barrier between groups of 25: a group that waits
# for its slowest member leaves the other workers idle, and a reasoning model's latency
# varies enough for that to cost real time. 25 is a chosen cap rather than a
# measured one — no run has yet been throttled by it.
VOTE_CONCURRENCY = 25

# Fixed by default, so one test pairs the same panelists with the same positions run
# after run. Separate from the panel's own seed because they answer different questions
# — who votes, versus which order each of them sees.
ORDER_SEED = 0


class OutOfCredit(Exception):
    """The provider refused payment (402): terminal for the run, free of charge.

    Raised by the adapter rather than letting the SDK's error through, because a 402
    arrives as the generic `APIStatusError` — indistinguishable *by type name* from
    any other odd status, and the type name is all a `VoteFailure` carries. Rejected
    requests are not charged, and the vote cache keeps what was already cast, so the
    remedy this failure names is top up and re-run, never re-pay.
    """


@dataclass(frozen=True)
class VoteUsage:
    """What one vote cost, as the provider reported it, and how long it took.

    - **Mixed provenance, on purpose:** the token counts and `cost` come from the
      provider's own usage block; `seconds` is measured locally, because none reports it.
    - **`reasoning_tokens` and `cost` are optional because absent is not zero.** Reasoning
      tokens bill at the output rate and are the largest single term, so a zero standing in
      for an unreported figure understates the bill by most of it — and a cost of 0.0 in a
      total that a budget decision reads is worse than an admitted gap.
    """

    input_tokens: int
    cached_tokens: int | None
    output_tokens: int
    reasoning_tokens: int | None
    cost: float | None
    seconds: float


@dataclass(frozen=True)
class VoteResponse:
    """One panelist's vote and what it cost to obtain.

    `usage` is optional for two different reasons: a test double should not have to
    invent token counts, and a provider that omits its usage block has still cast a
    perfectly good vote.
    """

    output: PanelVoteOutput
    usage: VoteUsage | None


@dataclass(frozen=True)
class UsageTotals:
    """A run's usage, summed — with how many votes each sum actually covers.

    - **The `*_reported` counts are not bookkeeping.** `reasoning_tokens` and `cost` are
      optional per vote, so a sum over the votes that reported them is a *partial* figure —
      and a partial figure presented as a total is how a run gets planned against a number
      that is quietly too small.
    - **Both time figures are needed; they answer different questions.** A wave finishes
      with its slowest member, so `seconds_slowest` is what a run's wall time is actually
      made of, while `seconds_total` beside it says how much of that work happened at once.
    - Both were measured per vote long before anything summed them here, which is why a
      slow run could not be explained from a log that reported only cost.
    """

    votes: int
    usage_reported: int
    input_tokens: int
    cached_tokens: int
    cached_reported: int
    output_tokens: int
    reasoning_tokens: int
    reasoning_reported: int
    cost: float
    cost_reported: int
    seconds_slowest: float
    seconds_total: float


def total_usage(usage: Sequence[VoteUsage | None]) -> UsageTotals:
    """Sum a run's per-vote usage, counting what each sum is a sum over."""
    reported = [u for u in usage if u is not None]
    cached = [u.cached_tokens for u in reported if u.cached_tokens is not None]
    reasoning = [u.reasoning_tokens for u in reported if u.reasoning_tokens is not None]
    cost = [u.cost for u in reported if u.cost is not None]
    return UsageTotals(
        votes=len(usage),
        usage_reported=len(reported),
        input_tokens=sum(u.input_tokens for u in reported),
        cached_tokens=sum(cached),
        cached_reported=len(cached),
        output_tokens=sum(u.output_tokens for u in reported),
        reasoning_tokens=sum(reasoning),
        reasoning_reported=len(reasoning),
        cost=sum(cost),
        cost_reported=len(cost),
        # `default=0.0` rather than a guard: a run of pure cache hits waited on
        # no model, and zero is the honest slowest, not a missing figure.
        seconds_slowest=max((u.seconds for u in reported), default=0.0),
        seconds_total=sum(u.seconds for u in reported),
    )


class PanelLLM(Protocol):
    # Everything the adapter itself contributes to what is asked — the model id
    # plus whatever it binds (the vote question, reasoning effort). It lives on the
    # adapter rather than travelling as separate parameters so the cache key
    # is fingerprinted against the ask that actually happens: a caller cannot hand
    # the pipeline one description and vote with another, and a knob added to the
    # adapter joins the key by extending this string, not the protocol.
    configuration: str

    def vote(
        self,
        *,
        system_prompt: str,
        option_1: str,
        option_2: str,
        enacted: str = "",
    ) -> VoteResponse: ...


@dataclass(frozen=True)
class VoteRequest:
    """Exactly what one panelist is asked, as the strings the model receives.

    Assembled in one place so the request that is sent and the request that is
    fingerprinted cannot drift apart — a fingerprint over a *reconstruction* of the
    question would go stale the moment the reconstruction and the assembly disagree.
    """

    system_prompt: str
    option_1: str
    option_2: str
    # The customer's audience words, as the approved second-person instruction —
    # raw, not fenced. Fencing is the adapter's job, below the fingerprint, for the
    # same reason the options are: the delimiter is a fresh random nonce, so a
    # fenced string would key a different digest on every restart and no cached
    # vote would ever be reachable again.
    enacted: str = ""


def build_vote_request(
    persona: Persona,
    presentation_order: list[str],
    *,
    variants: dict[str, str],
    enacted: str = "",
) -> VoteRequest:
    first_id, second_id = presentation_order
    return VoteRequest(
        system_prompt=render_persona_prompt(persona),
        option_1=variants[first_id],
        option_2=variants[second_id],
        enacted=enacted,
    )


def vote_fingerprint(request: VoteRequest, *, configuration: str) -> str:
    """The cache key for one vote: a digest of the question itself.

    Keying on the request's own strings plus the adapter's configuration is what
    makes invalidation automatic — change the persona template, a headline, the
    vote question's wording, or the model, and the key changes with it, so a stale
    entry cannot be served. The presentation order is already inside: a
    swapped order swaps option_1/option_2. JSON framing so no separator convention
    is needed for strings that may contain anything.
    """
    ingredients = [
        configuration,
        request.system_prompt,
        request.option_1,
        request.option_2,
    ]
    if request.enacted:
        # Appended only when there is one, so a run with no enacted context keys
        # exactly as it did before the field existed and every vote already in the
        # cache stays reachable. Not a special case: having no enacted context and
        # having an empty one are the same question, so they are the same key.
        ingredients.append(request.enacted)
    framed = json.dumps(ingredients)
    return hashlib.sha256(framed.encode()).hexdigest()


def presentation_orders(
    variant_ids: tuple[str, str], count: int, *, seed: int
) -> list[list[str]]:
    """One presentation order per panelist: an exact 50/50 split, then shuffled.

    Both halves are load-bearing and they fix different things.

    - **Exact split**, not a coin flip: the model picks the first-shown option 0.66 of the
      time (measured in docs/research/manipulation-check.md), so a surplus of one order is
      a bias on the top line rather than noise that averages out. An odd panel is off by
      one, which is as close as whole votes get.
    - **Shuffled**, because assigning by index parity — balanced as it is — ties
      who-sees-which-order to however the panel arrived, and the caller chooses that:
      `load_pool` returns id order, which groups by country. Nothing in the pipeline
      guarantees the panel is not sorted by something that matters.
    - **The odd vote's side is drawn, not fixed.** Handing the surplus to a fixed side
      would tilt every odd-sized panel the same way, which at a 0.66 first-position rate is
      a repeatable bias toward one variant — the same defect as index parity, just smaller.
    - **Seeded**, because `presentation_order` is stored per vote and a re-run of one test
      has to pair the same panelist with the same position to be the same test.
    """
    forward, reverse = list(variant_ids), list(reversed(variant_ids))
    rng = random.Random(seed)
    # A fresh list per panelist: these end up on a VoteRecord each, and repeating one
    # object `count` times would share it across every vote that saw that order.
    orders = [list(forward) for _ in range(count // 2)]
    orders += [list(reverse) for _ in range(count // 2)]
    if count % 2:
        orders.append(list(rng.choice((forward, reverse))))
    rng.shuffle(orders)
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
    """One panelist whose vote never arrived, and what stopped it.

    `error` is the exception's type and message, for diagnosis. It can carry provider
    response text and the model's own output, so it belongs in a log rather than in a
    response body.
    """

    persona_id: str
    error: str


@dataclass(frozen=True)
class PanelVotes:
    """What a panel returned: the votes cast, and who did not manage to cast one.

    - **`records` and `failures` travel together** because a verdict computed from
      `records` alone would silently be a verdict on a smaller panel than was asked for.
    - **Reporting the shortfall rather than raising** is the same division as retrieval's:
      the mechanism says what happened, and the caller decides whether a thinner panel
      still deserves a verdict. A caller that reads `records` and never looks at `failures`
      has made that decision by omission — the one reading this shape exists to prevent.
    - **`usage` runs parallel to `records`**, one entry each, holding `None` where the
      provider reported nothing. The per-vote list rather than a total, so a latency
      percentile stays available; `total_usage` derives the sums, which keeps them from
      drifting from the list they summarise.
    """

    records: list[VoteRecord]
    usage: tuple[VoteUsage | None, ...]
    failures: tuple[VoteFailure, ...]


def _cast_vote(
    persona: Persona,
    presentation_order: list[str],
    *,
    test_id: str,
    variants: dict[str, str],
    llm: PanelLLM,
    enacted: str = "",
) -> tuple[VoteRecord, VoteUsage | None]:
    """One panelist's vote and its cost, identity re-attached. Runs on a worker thread.

    The two are returned together so the collector can pair them in its own loop, where
    it already holds the persona. Accumulating usage inside the model adapter instead
    would need no lock either, but nothing would bound it to one run.
    """
    request = build_vote_request(
        persona, presentation_order, variants=variants, enacted=enacted
    )
    response = llm.vote(
        system_prompt=request.system_prompt,
        option_1=request.option_1,
        option_2=request.option_2,
        enacted=request.enacted,
    )
    record = VoteRecord(
        persona_id=persona.id,
        test_id=test_id,
        chosen_variant_id=resolve_choice(response.output.chosen, presentation_order),
        presentation_order=presentation_order,
        reason=response.output.reason,
    )
    return record, response.usage


def collect_panel_votes(
    *,
    test_id: str,
    variants: dict[str, str],
    panel: list[Persona],
    llm: PanelLLM,
    enacted: str = "",
    seed: int = ORDER_SEED,
    concurrency: int = VOTE_CONCURRENCY,
    orders: Sequence[list[str]] | None = None,
) -> PanelVotes:
    """Cast every panelist's vote concurrently, and report the ones that failed.

    - Each panelist sees the two variants in one of two orders, drawn from a balanced
      shuffled assignment, votes **positionally** (blind to which variant is which), and
      the position is resolved back to a variant id.
    - **`orders` overrides the internal draw** for callers that fixed the pairing before
      narrowing the panel: the cache split assigns orders to a whole chunk, then sends only
      the misses here, and a fresh draw over the smaller panel would re-pair panelists with
      positions.
    - **A vote that fails after the client's own retries costs that panelist and no other**
      — the remaining votes still stand, and the panel comes back short with the reason
      attached.
    - **Records are ordered by the panel**, never by which answers arrived first, so two
      runs of one test are comparable line by line.
    """
    if len(variants) != 2:
        raise ValueError(
            f"collect_panel_votes requires exactly 2 variants, got {len(variants)}"
        )

    first_id, second_id = variants
    if orders is None:
        orders = presentation_orders((first_id, second_id), len(panel), seed=seed)

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures: list[Future[tuple[VoteRecord, VoteUsage | None]]] = [
            pool.submit(
                _cast_vote,
                persona,
                order,
                test_id=test_id,
                variants=variants,
                llm=llm,
                enacted=enacted,
            )
            for persona, order in zip(panel, orders)
        ]

    records: list[VoteRecord] = []
    usage: list[VoteUsage | None] = []
    failures: list[VoteFailure] = []
    for persona, future in zip(panel, futures):
        error = future.exception()
        if error is None:
            record, vote_usage = future.result()
            records.append(record)
            usage.append(vote_usage)
            continue
        # A worker captures BaseException, so an interrupt raised inside one would
        # otherwise be filed as a panelist who declined to vote and the panel would
        # report success minus one.
        if not isinstance(error, Exception):
            raise error
        failures.append(
            VoteFailure(persona_id=persona.id, error=f"{type(error).__name__}: {error}")
        )
    return PanelVotes(records=records, usage=tuple(usage), failures=tuple(failures))
