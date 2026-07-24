"""Stage 2 — sample demographic records from a country's joint distribution.

Country-agnostic and deterministic: the per-country/per-format work all happened
offline in the pipeline, so this reads one joint table and draws from it.
Design: `issues/006b-demographics-sampler.md`.
"""

import csv
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field

from app.schemas import EducationLevel, Locale, PersonaDemographics

_JOINT_DIR = Path(__file__).parent / "data" / "joint"

# Earliest age a bachelor's can plausibly be held (3-year degrees, e.g. Germany).
# One global floor rather than a per-country table we can't maintain at scale.
_MIN_TERTIARY_AGE = 21


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
        return [JointCell.model_validate(row) for row in csv.DictReader(f)]


def _resolve_age(
    age_band: str, education: EducationLevel, rng: np.random.Generator
) -> int:
    """Pick a concrete age uniformly within a band ("20-29", or open-ended "80+").

    Tertiary is floored at `_MIN_TERTIARY_AGE`: uniform-within-band would otherwise
    emit degree holders too young to have plausibly finished university.
    """
    if age_band.endswith("+"):
        # No upper bound in the data; cap at Persona's max age.
        low, high = int(age_band[:-1]), 100
    else:
        lo, hi = age_band.split("-")
        low, high = int(lo), int(hi)
    if education is EducationLevel.TERTIARY:
        # Floor tertiary, but never past the band's top (guards impossible cells).
        low = min(max(low, _MIN_TERTIARY_AGE), high)
    return int(rng.integers(low, high + 1))


def sample_one(
    country: Locale, cells: list[JointCell], rng: np.random.Generator
) -> PersonaDemographics:
    """Draw one record from pre-loaded `cells`: a weighted cell, then a concrete age.

    Split out from `sample_demographics` so a caller that seeds per persona (the
    pool assembler, 006f) reuses the exact cell-choice + age-resolution logic
    without reloading the table each draw. No country-specific logic here — the
    heterogeneity was all resolved offline into the joint table.
    """
    weights = np.array([cell.weight for cell in cells])
    cell = cells[int(rng.choice(len(cells), p=weights / weights.sum()))]
    return PersonaDemographics(
        country=country,
        age=_resolve_age(cell.age_band, cell.education, rng),
        gender=cell.gender,
        income_quintile=cell.income_quintile,
        education=cell.education,
    )


def sample_demographics(
    country: Locale, n: int, *, seed: int
) -> list[PersonaDemographics]:
    """Draw `n` demographic records for `country`; deterministic for a given seed."""
    cells = load_joint(country)
    rng = np.random.default_rng(seed)
    return [sample_one(country, cells, rng) for _ in range(n)]
