"""Stage 2 — sample demographic records from a country's joint distribution.

Country-agnostic and deterministic: the per-country/per-format work all happened
offline in the pipeline, so this reads one joint table and draws from it.
Design: `issues/006b-demographics-sampler.md`.
"""

import csv
import random
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas import EducationLevel, Locale, PersonaDemographics

_JOINT_DIR = Path(__file__).parent / "data" / "joint"


class JointCell(BaseModel):
    """One cell of a country's joint distribution (a row of its committed CSV)."""

    age_band: str
    gender: Literal["male", "female"]
    education: EducationLevel
    income_quintile: int = Field(ge=1, le=5)
    weight: float = Field(gt=0)


def load_joint(country: Locale) -> list[JointCell]:
    """Return the joint cells for `country` — the single place storage is touched.

    A DB swap would happen here alone. Validating each row into a `JointCell`
    means a malformed joint file fails loudly at load, not silently mid-sample.
    """
    path = _JOINT_DIR / f"{country.value.lower()}.csv"
    with path.open(newline="") as f:
        # Provenance may be carried in leading '#' lines; skip them before the header.
        reader = csv.DictReader(line for line in f if not line.startswith("#"))
        return [JointCell.model_validate(row) for row in reader]


def _resolve_age(age_band: str, rng: random.Random) -> int:
    """Pick a concrete age uniformly within a band ("20-29", or open-ended "80+")."""
    if age_band.endswith("+"):
        # The data has no upper bound here; cap at Persona's max age.
        return rng.randint(int(age_band[:-1]), 100)
    low, high = age_band.split("-")
    return rng.randint(int(low), int(high))


def sample_demographics(
    country: Locale, n: int, *, seed: int
) -> list[PersonaDemographics]:
    """Draw `n` demographic records for `country`; deterministic for a given seed.

    Cells are drawn with probability proportional to their weight, then the band
    is resolved to a concrete age. No country-specific logic lives here — the
    heterogeneity was all resolved offline into the joint table.
    """
    cells = load_joint(country)
    rng = random.Random(seed)
    chosen = rng.choices(cells, weights=[cell.weight for cell in cells], k=n)
    return [
        PersonaDemographics(
            country=country,
            age=_resolve_age(cell.age_band, rng),
            gender=cell.gender,
            income_quintile=cell.income_quintile,
            education=cell.education,
        )
        for cell in chosen
    ]
