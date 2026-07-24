"""Assemble fully-specified personas from the sampled + synthesized parts.

Pure and side-effect-free (no DB): given a country, a slot index, and the master
seed, produce a deterministic, per-slot-independent persona.
"""

from collections.abc import Container, Iterator
from dataclasses import dataclass

import numpy as np

from app.bigfive import sample_big_five
from app.interests import Embedder, InterestLLM, embed_interests, synthesize_interests
from app.sampler import JointCell, load_joint, sample_one
from app.schemas import Locale, Persona

# Zero-pad the ordinal: a 5k pool needs 4 digits; 5 leaves headroom and keeps ids
# lexically sortable within a country.
_ID_WIDTH = 5


@dataclass(frozen=True)
class AssembledPersona:
    """A persona plus its per-interest embeddings, aligned 1:1 with `interests`."""

    persona: Persona
    interest_vectors: list[list[float]]


def persona_id(country: Locale, index: int) -> str:
    """Stable ordinal id, e.g. `US-00042` — a label, never parsed."""
    return f"{country.value}-{index:0{_ID_WIDTH}d}"


def _country_entropy(country: Locale) -> int:
    """Per-country seed entropy from the country code itself, so adding a country
    needs no table here and enum reordering can't reshuffle existing pools.
    """
    return int.from_bytes(country.value.encode(), "big")


def _slot_rngs(
    master_seed: int, country: Locale, index: int
) -> tuple[np.random.Generator, np.random.Generator]:
    """Independent (demographics, Big Five) RNGs for one slot.

    Seeding each slot from (master_seed, country, index) — rather than drawing
    from one shared stream — makes slot i the same person at any pool size, so
    the dev subset is a true prefix of the full pool and the pool can be extended
    without disturbing existing personas.
    """
    demo_seq, big_five_seq = np.random.SeedSequence(
        [master_seed, _country_entropy(country), index]
    ).spawn(2)
    return np.random.default_rng(demo_seq), np.random.default_rng(big_five_seq)


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

    `cells` are passed in so the caller loads a country's joint table once rather
    than per persona.
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
    skip: Container[str] = frozenset(),
) -> Iterator[AssembledPersona]:
    """Yield the pool one persona at a time (sequential, lazy).

    `quotas` is the per-country count — the one hand-managed cross-country knob.
    `skip` holds persona ids to leave un-generated, so a resumed seed never pays
    to assemble (or call the LLM for) personas it already persisted.
    """
    for country, n in quotas.items():
        cells = load_joint(country)
        for index in range(n):
            if persona_id(country, index) in skip:
                continue
            yield assemble_persona(
                country,
                index,
                cells,
                master_seed=master_seed,
                llm=llm,
                embedder=embedder,
            )
