"""Stage 1 — build a country's joint from the OECD SDMX API (+ World Bank PIP for income).

Replaces the per-country national builders: one keyless API, queried by country code.
`age × gender × education` come as direct OECD cross-tabs (education native ISCED-2011);
income attaches as an imputed marginal (declared). Design: issues/006b (2026-07-22 amendment).
"""

import csv
import io
from collections import defaultdict

from app.schemas import EducationLevel


# OECD reports attainment on ISCED-2011 already; these three aggregates are
# exactly our collapse (below-secondary / secondary / tertiary).
_ISCED_TO_EDUCATION = {
    "ISCED11A_0T2": EducationLevel.BELOW_SECONDARY,
    "ISCED11A_3_4": EducationLevel.SECONDARY,
    "ISCED11A_5T8": EducationLevel.TERTIARY,
}


def parse_sdmx_csv(text: str, dims: tuple[str, ...]) -> dict[tuple[str, ...], float]:
    """Read an SDMX-CSV response into OBS_VALUE keyed by the given dimensions.

    Stays format-dumb: it only knows the SDMX-CSV convention of one column per
    dimension plus an OBS_VALUE column. Which dimensions form the key, and any
    scaling of the value, are the caller's concern.
    """
    reader = csv.DictReader(io.StringIO(text))
    return {
        tuple(row[dim] for dim in dims): float(row["OBS_VALUE"]) for row in reader
    }


def _isced_to_education(code: str) -> EducationLevel:
    return _ISCED_TO_EDUCATION[code]


def _sex_to_gender(code: str) -> str:
    return {"F": "female", "M": "male"}[code]


def _low_age(group: str) -> int:
    """Lower bound of an OECD 5-year age group id ("Y25T29" -> 25, "Y_GE85" -> 85)."""
    body = group[1:]
    if body.startswith("_GE"):
        return int(body[3:])
    return int(body.split("T")[0])


def _dl_band_for_5yr(group: str) -> str:
    """Map a 5-year population group to its D&L band.

    Y15T19 lands in 18-19 (the only band above our 18 floor it touches); its
    below-floor fraction is dropped when weighting. Groups from 20 up fall in
    one decade band by their lower bound; 80+ is the open top band.
    """
    low = _low_age(group)
    if low < 20:
        return "18-19"
    if low >= 80:
        return "80+"
    start = (low // 10) * 10
    return f"{start}-{start + 9}"


def _edu_band_for_5yr(group: str) -> str:
    """Map a 5-year population group to the education band supplying its P(edu|·).

    Education is observed only for 25-64. Below 25 and 65+ have no data, so they
    borrow the nearest observed band (Y25T34 / Y55T64) — a better prior than a
    pooled mean since attainment is age-ordered. Declared imputed by the caller.
    """
    low = _low_age(group)
    if low < 25:
        return "Y25T34"
    if low >= 65:
        return "Y55T64"
    start = 25 + ((low - 25) // 10) * 10
    return f"Y{start}T{start + 9}"


# P(income quintile | education): a fixed, monotone prior with spread — income
# is grounded on education (the strongest predictor), but each row keeps mass
# across quintiles so educated-poor / uneducated-rich personas survive. Declared
# imputed; swap for per-country OECD earnings behind this table if drift warrants.
_INCOME_SPLIT: dict[EducationLevel, tuple[float, float, float, float, float]] = {
    EducationLevel.BELOW_SECONDARY: (0.35, 0.28, 0.20, 0.12, 0.05),
    EducationLevel.SECONDARY: (0.20, 0.22, 0.22, 0.20, 0.16),
    EducationLevel.TERTIARY: (0.08, 0.14, 0.20, 0.28, 0.30),
}


def attach_income(
    combined: dict[tuple[str, str, EducationLevel], float],
) -> dict[tuple[str, str, EducationLevel, int], float]:
    """Expand each age×gender×education cell into five income-quintile cells.

    The cell's weight is split across quintiles by `_INCOME_SPLIT[education]`,
    so mass is conserved and income skews with education.
    """
    joint: dict[tuple[str, str, EducationLevel, int], float] = {}
    for (band, gender, edu), weight in combined.items():
        for quintile, share in enumerate(_INCOME_SPLIT[edu], start=1):
            joint[(band, gender, edu, quintile)] = weight * share
    return joint


def _floor_fraction(group: str) -> float:
    """Share of a 5-year group at or above the 18 age floor.

    Only Y15T19 straddles it: of ages 15-19, just 18-19 count, so 2/5. Every
    other group is wholly above 18.
    """
    return 0.4 if group == "Y15T19" else 1.0


def combine(
    population: dict[tuple[str, str], float],
    education: dict[tuple[str, str, str], float],
) -> dict[tuple[str, str, EducationLevel], float]:
    """Cross population with education shares into an age×gender×education joint.

    `population` is (5-year group, sex) -> count; `education` is
    (education band, sex, ISCED) -> P(edu | band, sex). Each 5-year group takes
    its containing/nearest education band's shares, weighted by its population,
    then groups summing to the same D&L band blend together.
    """
    edu_index: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
    for (band, sex, isced), share in education.items():
        edu_index[(band, sex)][isced] = share

    joint: dict[tuple[str, str, EducationLevel], float] = defaultdict(float)
    for (group, sex), pop in population.items():
        weight = pop * _floor_fraction(group)
        gender = _sex_to_gender(sex)
        dl_band = _dl_band_for_5yr(group)
        shares = edu_index[(_edu_band_for_5yr(group), sex)]
        for isced, share in shares.items():
            joint[(dl_band, gender, _isced_to_education(isced))] += weight * share
    return dict(joint)
