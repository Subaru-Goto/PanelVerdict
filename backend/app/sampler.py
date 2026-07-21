"""Stage 2 — sample demographic records from a country's joint distribution.

Country-agnostic and deterministic: the per-country/per-format work all happened
offline in the pipeline. Here we just read a joint table and draw from it.
Design: `issues/006b-demographics-sampler.md`.
"""

import random
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas import EducationLevel, Locale, PersonaDemographics


class JointCell(BaseModel):
    """One cell of a country's joint distribution (a row of its committed CSV)."""

    age_band: str
    gender: Literal["male", "female"]
    education: EducationLevel
    income_quintile: int = Field(ge=1, le=5)
    weight: float = Field(gt=0)


def load_joint(country: Locale) -> list[JointCell]:
    """The storage seam: return the joint cells for `country`.

    The ONLY place storage is touched — reads the committed CSV today; swap to a
    DB here later without changing the sampler. Reads
    `app/data/joint/<country>.csv`.
    """
    # TODO: resolve the path (Path(__file__).parent / "data" / "joint" / f"{country.value.lower()}.csv")
    # TODO: read rows (stdlib csv.DictReader; skip any comment lines)
    # TODO: build a JointCell per row (pydantic validates types/ranges here)
    ...


def _resolve_age(age_band: str, rng: random.Random) -> int:
    """Resolve a band string ("20-29", or open-ended "80+") to a concrete age.

    Uniform within the band — a v1 approximation (flattens the within-band slope).
    """
    # TODO: parse "a-b" → (a, b); handle "80+" (cap at Persona's max, 100)
    # TODO: return rng.randint(a, b)
    ...


def sample_demographics(
    country: Locale, n: int, *, seed: int
) -> list[PersonaDemographics]:
    """Draw `n` demographic records for `country`. Deterministic for a given seed.

    Weighted-pick cells ∝ their weight, then resolve each `age_band` to a concrete
    age. This is the whole of stage 2 — no country-specific logic lives here.
    """
    # TODO: cells = load_joint(country)
    # TODO: rng = random.Random(seed)
    # TODO: chosen = rng.choices(cells, weights=[c.weight for c in cells], k=n)
    # TODO: for each cell → PersonaDemographics(country=country,
    #         age=_resolve_age(cell.age_band, rng), gender=cell.gender,
    #         income_quintile=cell.income_quintile, education=cell.education)
    # TODO: return the list
    ...
