"""Stage 1 — build a country's joint from the OECD SDMX API (+ World Bank PIP for income).

Replaces the per-country national builders: one keyless API, queried by country code.
`age × gender × education` come as direct OECD cross-tabs (education native ISCED-2011);
income attaches as an imputed marginal (declared). Design: issues/006b (2026-07-22 amendment).
"""

from app.schemas import EducationLevel


# OECD reports attainment on ISCED-2011 already; these three aggregates are
# exactly our collapse (below-secondary / secondary / tertiary).
_ISCED_TO_EDUCATION = {
    "ISCED11A_0T2": EducationLevel.BELOW_SECONDARY,
    "ISCED11A_3_4": EducationLevel.SECONDARY,
    "ISCED11A_5T8": EducationLevel.TERTIARY,
}


def _isced_to_education(code: str) -> EducationLevel:
    return _ISCED_TO_EDUCATION[code]


def _sex_to_gender(code: str) -> str:
    return {"F": "female", "M": "male"}[code]
