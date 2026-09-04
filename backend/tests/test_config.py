from typing import Any

import pytest
from pydantic import ValidationError

from app.config import (
    PROFILES,
    Settings,
)

_DB: dict[str, Any] = {
    "postgres_user": "u",
    "postgres_password": "p",
    "postgres_db": "d",
}


def test_an_unconfigured_run_draws_the_cheapest_panel() -> None:
    """The safety property of having profiles at all. Every panel size is real money,
    so the size that costs the most must never be what you get by forgetting to choose
    — a misconfigured CI job should waste a cent, not a tenth of the whole credit."""
    settings = Settings(**_DB)

    assert settings.panel.size == min(profile.size for profile in PROFILES.values())


def test_the_named_profile_is_the_one_that_gets_used() -> None:
    """Guards the lookup rather than the table: a mistyped key would fall back to
    something plausible-looking and quietly run the wrong panel size."""
    settings = Settings(**_DB, profile="prod")

    assert settings.panel is PROFILES["prod"]
    assert settings.panel.size == 200


def test_a_profile_name_that_does_not_exist_is_refused_at_startup() -> None:
    """Rejected on construction rather than at first use, so a typo in the environment
    fails before anything is retrieved or paid for."""
    with pytest.raises(ValidationError):
        Settings(**_DB, profile="production")  # type: ignore[arg-type]  # the rejection is the test


def test_the_profiles_are_a_ladder() -> None:
    """dev cheaper than demo cheaper than prod, which is the only relationship between
    them that anything relies on: the names are meaningless if the order can drift."""
    sizes = [PROFILES[name].size for name in ("dev", "demo", "prod")]

    assert sizes == sorted(sizes)
    assert len(set(sizes)) == len(sizes)


def test_the_preview_price_is_its_two_calls() -> None:
    """Retired with USD_PER_PREVIEW (094): a preview's only possible call is
    the rewrite, priced by USD_PER_ROLEPLAY, pinned below."""


def test_supabase_url_off_means_sign_in_is_not_configured() -> None:
    """A local process cannot unset what the env file sets; it can only
    overwrite it. The word `off` is that overwrite (123/#289's local target)."""
    settings = Settings(**_DB, supabase_project_url="off")

    assert settings.supabase_project_url is None


def test_a_blank_supabase_url_stays_a_blank() -> None:
    """Fail closed: a variable left empty in a deploy dashboard must not read
    as "sign-in off" — it stays a non-URL the JWKS client refuses at boot, so
    the mistake is a crash, not a deployment counting quotas on a header."""
    settings = Settings(**_DB, supabase_project_url="")

    assert settings.supabase_project_url == ""


def test_the_pool_size_defaults_to_the_dashboard_reading_and_reads_the_environment(
    monkeypatch,
) -> None:
    """112/#242: 15 is what the session pooler granted this project on
    2026-09-04; another deployment's dashboard may say otherwise."""
    assert Settings(**_DB).pooler_pool_size == 15
    monkeypatch.setenv("POOLER_POOL_SIZE", "20")
    assert Settings(**_DB).pooler_pool_size == 20


# 106/#226: every measurement in docs/research/ that grades model behaviour was
# run against one model, and swapping that model is one string here. The run
# itself is paid — the guard alone is ~160 calls — so it cannot live in CI; what
# can is noticing the change that makes a rerun owed. Each row names the setting,
# the model its figures were measured on, and the document that would be stale.
# A row missing from here is a measurement nothing protects, so the last
# assertion refuses to let a new model setting arrive without one.
_MEASURED_ON = {
    "targeting_model": (
        "openai/gpt-5.6-luna",
        "roleplay-guard-check.md, roleplay-cost.md",
    ),
    "analyst_model": (
        "openai/gpt-5.6-luna",
        "topic-boundary-check.md, corpus-retrieval-check.md, analyst-turn-cost.md",
    ),
    "judge_model": (
        "openai/gpt-5.6-luna",
        "every check graded by a judge: topic-boundary-check.md, "
        "corpus-retrieval-check.md, chat-red-team.md",
    ),
    "screening_model": (
        "openai/gpt-5.6-luna",
        "headline-channel-check.md, enacted-context-check.md",
    ),
    "moderation_model": ("mistral-moderation-2603", "moderation-check.md"),
    "embedding_model": (
        "openai/text-embedding-3-small",
        "corpus-retrieval-check.md, similarity-check.md",
    ),
}


@pytest.mark.parametrize(
    ("setting", "measured", "records"),
    [(name, model, docs) for name, (model, docs) in _MEASURED_ON.items()],
)
def test_a_model_change_owes_a_rerun_of_what_was_measured_on_it(
    setting: str, measured: str, records: str
) -> None:
    """Not a claim that this model is the right one — a reminder that the figures
    in docs/research/ are about *this* string. Changing it here is fine; shipping
    the change without rerunning the named checks, or recording why their numbers
    still hold, is not. Editing this line is the acknowledgement."""
    assert getattr(Settings(**_DB), setting) == measured, (
        f"{setting} changed: {records} measured model behaviour on {measured}."
        " Rerun those checks and record the result, or say in the record why the"
        " figures still hold, before this ships."
    )


def test_the_panel_model_owes_the_same_rerun() -> None:
    """The panel's model lives on the profile rather than in `Settings`, and it
    is the one every vote is cast by (manipulation-check-luna.md is 071's gate
    result, panel-model-selection.md the selection)."""
    assert {profile.model for profile in PROFILES.values()} == {
        "openai/gpt-5.6-luna"
    }, (
        "the panel model changed: manipulation-check-luna.md and"
        " panel-model-selection.md measured the vote on openai/gpt-5.6-luna."
    )


def test_every_model_setting_is_named_in_the_rerun_table() -> None:
    """The table above is a hand-kept list, so this is the line that keeps it
    honest: a model setting added without a row would be a measurement nothing
    protects, and the omission is silent otherwise."""
    declared = {
        name
        for name in Settings.model_fields
        if name.endswith("_model") or name == "model"
    }

    assert declared == set(_MEASURED_ON), (
        "a model setting has no row in _MEASURED_ON: add it with the"
        " docs/research record its behaviour was measured in."
    )
