"""Per-country hobby banks feeding the interest-generation prompt.

The model echoes its prompt examples, so a static example list collapses the
pool onto itself. Each persona instead gets its own draw from a per-country,
two-tier bank — the observed anchoring then *injects* variety and country
priors, which matters because the interest model rejects a temperature knob.

Bank entries are prompt examples, never a menu: nothing gates generated
interests to bank membership. Content is LLM-drafted and human-skimmed —
rough popularity tiers, not survey data (the model supplies the fit; the bank
only decorrelates and re-centers on the mainstream).

Entry convention — participation vs spectating are different interests, so:
"playing X" for doing a sport, "watching X" for following it, bare form only
where unambiguous ("fishing", "baking"). Tiers apply per form: watching
football is common in the US while playing it as an adult is not.
"""

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import BaseModel

from app.schemas import Locale

_HOBBY_DIR = Path(__file__).parent / "data" / "hobbies"

_N_COMMON_EXAMPLES = 3
_N_NICHE_EXAMPLES = 1


class _HobbyRow(BaseModel):
    """One row of a country's committed bank CSV."""

    hobby: str
    tier: Literal["common", "niche"]


@dataclass(frozen=True)
class HobbyBank:
    common: tuple[str, ...]
    niche: tuple[str, ...]


def load_hobby_bank(country: Locale) -> HobbyBank:
    """Return the hobby bank for `country` — the single place storage is touched.

    Validating each row into a `_HobbyRow` means a malformed bank file fails
    loudly at load, not silently mid-seed.
    """
    path = _HOBBY_DIR / f"{country.value.lower()}.csv"
    with path.open(newline="") as f:
        rows = [_HobbyRow.model_validate(row) for row in csv.DictReader(f)]
    return HobbyBank(
        common=tuple(row.hobby for row in rows if row.tier == "common"),
        niche=tuple(row.hobby for row in rows if row.tier == "niche"),
    )


def sample_prompt_examples(bank: HobbyBank, rng: np.random.Generator) -> list[str]:
    """One persona's prompt examples: mostly mainstream plus one distinctive."""
    picks = [
        bank.common[i]
        for i in rng.choice(len(bank.common), size=_N_COMMON_EXAMPLES, replace=False)
    ] + [
        bank.niche[i]
        for i in rng.choice(len(bank.niche), size=_N_NICHE_EXAMPLES, replace=False)
    ]
    # shuffle so the niche example isn't always in the same position — a fixed
    # slot would teach the model "always end with the quirky one"
    return [picks[i] for i in rng.permutation(len(picks))]
