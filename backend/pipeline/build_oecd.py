"""Stage 1 — build a country's demographic joint from the OECD SDMX API.

One keyless API, queried by country code. `age × gender × education` come as
direct OECD cross-tabs (education native ISCED-2011); income attaches as an
imputed marginal (declared). Design: issues/006b.
"""

import csv
import io
import json
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from app.sampler import JointCell
from app.schemas import EducationLevel, Locale


class BuildResult(BaseModel):
    """A country's built joint plus the fidelity it was built at."""

    country: Locale
    rows: list[JointCell]
    income_marginal: list[float]  # realized, population-weighted quintile shares
    imputations: list[str]


# OECD reports attainment on ISCED-2011 already; these three aggregates are
# exactly our collapse (below-secondary / secondary / tertiary).
_ISCED_TO_EDUCATION = {
    "ISCED11A_0T2": EducationLevel.BELOW_SECONDARY,
    "ISCED11A_3_4": EducationLevel.SECONDARY,
    "ISCED11A_5T8": EducationLevel.TERTIARY,
}


_REF_AREA: dict[Locale, str] = {Locale.US: "USA", Locale.JP: "JPN", Locale.DE: "DEU"}

_SDMX_BASE = "https://sdmx.oecd.org/public/rest/data"
_POP_FLOW = "OECD.ELS.SAE,DSD_POPULATION@DF_POP_HIST"
_EDU_FLOW = "OECD.EDU.IMEP,DSD_EAG_LSO_EA@DF_LSO_NEAC_DISTR_EA"
_POP_AGES = (
    "Y15T19+Y20T24+Y25T29+Y30T34+Y35T39+Y40T44+Y45T49+Y50T54"
    "+Y55T59+Y60T64+Y65T69+Y70T74+Y75T79+Y80T84+Y_GE85"
)
_EDU_AGES = "Y25T34+Y35T44+Y45T54+Y55T64"
_EDU_ATTAIN = "ISCED11A_0T2+ISCED11A_3_4+ISCED11A_5T8"

_IMPUTATIONS = [
    "education below 25 and 65+ borrow the nearest observed band (25-34 / 55-64)",
    "18-19 taken as 2/5 of the 15-19 population band",
    "income quintile conditioned on education only, via a fixed prior",
]

# High-completion peers whose below/secondary split stands in when a country
# reports only tertiary (e.g. JP). Chosen for similarity, not averaged blindly.
_SPLIT_PEERS: tuple[Locale, ...] = (Locale.US, Locale.DE)


def _ref_area(country: Locale) -> str:
    return _REF_AREA[country]


def _pop_url(country: Locale) -> str:
    key = f"{_ref_area(country)}.POP.PS.M+F.{_POP_AGES}.H"
    return f"{_SDMX_BASE}/{_POP_FLOW}/{key}?lastNObservations=1"


def _edu_url(country: Locale) -> str:
    key = f"{_ref_area(country)}.M+F.{_EDU_AGES}.{_EDU_ATTAIN}..........OBS..."
    return f"{_SDMX_BASE}/{_EDU_FLOW}/{key}?lastNObservations=1"


def _fetch_education(
    country: Locale, fetch: Callable[[str], str]
) -> dict[tuple[str, str, str], float]:
    """Fetch a country's education cross-tab as (age, sex, ISCED) -> share."""
    percent = parse_sdmx_csv(fetch(_edu_url(country)), ("AGE", "SEX", "ATTAINMENT_LEV"))
    return {key: value / 100 for key, value in percent.items()}


def build_oecd(country: Locale, *, fetch: Callable[[str], str]) -> "BuildResult":
    """Build a country's joint from the OECD API via an injected `fetch`.

    `fetch(url) -> csv text` is injected so the orchestration is unit-testable
    without network. Education percentages are normalised to shares here — the
    one place that knows OECD reports attainment as a percent.
    """
    population = parse_sdmx_csv(fetch(_pop_url(country)), ("AGE", "SEX"))
    education = _fetch_education(country, fetch)
    imputations = list(_IMPUTATIONS)
    if _education_is_incomplete(education):
        peers = [p for p in _SPLIT_PEERS if p != country]
        education = _complete_education_from_peers(
            education, [_fetch_education(p, fetch) for p in peers]
        )
        names = ", ".join(p.value for p in peers)
        imputations.append(
            f"missing attainment level(s) completed from peers ({names})"
        )

    joint = attach_income(combine(population, education))
    rows = [
        JointCell(
            age_band=band,
            gender=gender,
            education=education_level,
            income_quintile=quintile,
            weight=weight,
        )
        for (band, gender, education_level, quintile), weight in joint.items()
        if weight > 0
    ]
    total = sum(joint.values())
    marginal = [
        sum(w for (*_, q), w in joint.items() if q == quintile) / total
        for quintile in range(1, 6)
    ]
    return BuildResult(
        country=country,
        rows=rows,
        income_marginal=marginal,
        imputations=imputations,
    )


_JOINT_COLUMNS = ["age_band", "gender", "education", "income_quintile", "weight"]


def write_joint(result: BuildResult, dest_dir: Path) -> None:
    """Write the joint CSV (what the sampler reads) plus a fidelity sidecar.

    The CSV columns mirror `JointCell` so `load_joint` reconstructs the cells
    verbatim; the `.meta.json` carries the fidelity the CSV can't (realized
    income marginal, declared imputations, source).
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    stem = result.country.value.lower()
    with (dest_dir / f"{stem}.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_JOINT_COLUMNS)
        writer.writeheader()
        for cell in result.rows:
            writer.writerow(
                {
                    "age_band": cell.age_band,
                    "gender": cell.gender,
                    "education": cell.education.value,
                    "income_quintile": cell.income_quintile,
                    "weight": cell.weight,
                }
            )
    meta = {
        "country": result.country.value,
        "source": [_POP_FLOW, _EDU_FLOW],
        "income_marginal": result.income_marginal,
        "imputations": result.imputations,
    }
    (dest_dir / f"{stem}.meta.json").write_text(json.dumps(meta, indent=2) + "\n")


def _http_fetch(url: str) -> str:
    import urllib.request

    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.sdmx.data+csv; version=2.0",
            "User-Agent": "Mozilla/5.0 (panelverdict pipeline)",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode()


def parse_sdmx_csv(text: str, dims: tuple[str, ...]) -> dict[tuple[str, ...], float]:
    """Read an SDMX-CSV response into OBS_VALUE keyed by the given dimensions.

    Stays format-dumb: it only knows the SDMX-CSV convention of one column per
    dimension plus an OBS_VALUE column. Which dimensions form the key, and any
    scaling of the value, are the caller's concern.
    """
    reader = csv.DictReader(io.StringIO(text))
    return {
        tuple(row[dim] for dim in dims): float(row["OBS_VALUE"])
        for row in reader
        if row["OBS_VALUE"] != ""  # empty = no observation (e.g. JP's missing split)
    }


def _isced_to_education(code: str) -> EducationLevel:
    return _ISCED_TO_EDUCATION[code]


def _sex_to_gender(code: str) -> str:
    return {"F": "female", "M": "male"}[code]


_EDUCATION_ISCED = ("ISCED11A_0T2", "ISCED11A_3_4", "ISCED11A_5T8")


def _education_is_incomplete(education: dict[tuple[str, str, str], float]) -> bool:
    """True if any age×sex cell is missing one of the three attainment levels.

    Country-agnostic: it detects a gap of any shape (e.g. JP reports only
    tertiary), not a specific missing level.
    """
    cells = {(age, sex) for (age, sex, _) in education}
    return any(
        (age, sex, isced) not in education
        for age, sex in cells
        for isced in _EDUCATION_ISCED
    )


def _complete_education_from_peers(
    education: dict[tuple[str, str, str], float],
    peers: list[dict[tuple[str, str, str], float]],
) -> dict[tuple[str, str, str], float]:
    """Fill whichever attainment levels a country omits, from peers.

    Works for any gap shape, not just JP's tertiary-only: per age×sex, the
    unreported mass (1 - sum of reported) is spread across the missing levels in
    proportion to the peers' mean shares of those same levels, so a similar peer
    group carries over its structure (and its age gradient). Reported levels stay
    exact. Declared imputed by the caller.
    """
    cells = {(age, sex) for (age, sex, _) in education}
    filled = dict(education)
    for age, sex in cells:
        reported = {
            isced: education[(age, sex, isced)]
            for isced in _EDUCATION_ISCED
            if (age, sex, isced) in education
        }
        missing = [isced for isced in _EDUCATION_ISCED if isced not in reported]
        if not missing:
            continue
        missing_mass = 1.0 - sum(reported.values())
        peer_share = {
            isced: sum(peer[(age, sex, isced)] for peer in peers) / len(peers)
            for isced in missing
        }
        total = sum(peer_share.values())
        for isced in missing:
            filled[(age, sex, isced)] = missing_mass * peer_share[isced] / total
    return filled


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


if __name__ == "__main__":
    import sys

    country = Locale(sys.argv[1])
    dest = Path(__file__).parents[1] / "app" / "data" / "joint"
    result = build_oecd(country, fetch=_http_fetch)
    write_joint(result, dest)
    print(
        f"wrote {country.value}: {len(result.rows)} rows; "
        f"income_marginal={[round(x, 3) for x in result.income_marginal]}"
    )
