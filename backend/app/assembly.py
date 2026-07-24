"""Assemble fully-specified personas from the sampled + synthesized parts.

Pure and side-effect-free (no DB): given a country, a slot index, and the master
seed, produce a deterministic, per-slot-independent persona. Persistence (006f
PR-2) consumes what this emits. Design: issues/006f-persistence.md (D3, D5).
"""

import random
from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np

from app.bigfive import sample_big_five
from app.interests import Embedder, InterestLLM, embed_interests, synthesize_interests
from app.sampler import JointCell, load_joint, sample_one
from app.schemas import Locale, Persona

# Zero-pad the ordinal: a 5k pool needs 4 digits; 5 leaves headroom and keeps ids
# lexically sortable within a country.
_ID_WIDTH = 5

# Stable per-country entropy for per-slot seeding — fixed values (not Locale's
# definition order) so reordering the enum can't silently reshuffle a pool.
_COUNTRY_ENTROPY: dict[Locale, int] = {Locale.US: 0, Locale.JP: 1, Locale.DE: 2}


@dataclass(frozen=True)
class AssembledPersona:
    """A persona plus its per-interest embeddings, aligned 1:1 with `interests`."""

    persona: Persona
    interest_vectors: list[list[float]]


def persona_id(country: Locale, index: int) -> str:
    """Stable ordinal id, e.g. `US-00042` (006f D3) — a label, never parsed."""
    return f"{country.value}-{index:0{_ID_WIDTH}d}"


def _slot_rngs(
    master_seed: int, country: Locale, index: int
) -> tuple[random.Random, np.random.Generator]:
    """Independent (demographics, Big Five) RNGs for one slot.

    Seeding each slot from (master_seed, country, index) — rather than drawing
    from one shared stream — makes slot i the same person at any pool size, so
    the dev subset is a true prefix of the full pool and the pool can be extended
    without disturbing existing personas (006f D3).
    """
    demo_seq, big_five_seq = np.random.SeedSequence(
        [master_seed, _COUNTRY_ENTROPY[country], index]
    ).spawn(2)
    demo_seed = int(demo_seq.generate_state(1, dtype=np.uint64)[0])
    return random.Random(demo_seed), np.random.default_rng(big_five_seq)


def assemble_persona(
    country: Locale,
    index: int,
    cells: list[JointCell],
    *,
    master_seed: int,
    llm: InterestLLM,
    embedder: Embedder,
) -> AssembledPersona:
    """Build one persona deterministically from its slot.

    Sample demographics + Big Five from the slot's own RNGs, synthesize + screen
    interests, embed them, and assemble. `cells` are passed in so the caller loads
    a country's joint table once rather than per persona.
    """
    demo_rng, big_five_rng = _slot_rngs(master_seed, country, index)
    demographics = sample_one(country, cells, demo_rng)
    big_five = sample_big_five(demographics.age, demographics.gender, big_five_rng)
    interests = synthesize_interests(demographics, big_five, llm=llm)
    return AssembledPersona(
        persona=Persona(
            id=persona_id(country, index),
            **demographics.model_dump(),
            interests=interests,
            big_five=big_five,
        ),
        interest_vectors=embed_interests(interests, embedder=embedder),
    )


def assemble_pool(
    quotas: dict[Locale, int],
    *,
    master_seed: int,
    llm: InterestLLM,
    embedder: Embedder,
) -> Iterator[AssembledPersona]:
    """Yield the pool one persona at a time (sequential, lazy).

    `quotas` is the per-country count — the one hand-managed cross-country knob
    (D3). Yielding lazily lets the seed script persist as it goes (one transaction
    per persona); threading + the persistence layer sit on top of this (006f PR-3).
    """
    for country, n in quotas.items():
        cells = load_joint(country)
        for index in range(n):
            yield assemble_persona(
                country,
                index,
                cells,
                master_seed=master_seed,
                llm=llm,
                embedder=embedder,
            )
