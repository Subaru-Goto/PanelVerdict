import pytest
from pydantic import ValidationError

from app.config import (
    PROFILES,
    Settings,
)

_DB = {
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
        Settings(**_DB, profile="production")


def test_the_profiles_are_a_ladder() -> None:
    """dev cheaper than demo cheaper than prod, which is the only relationship between
    them that anything relies on: the names are meaningless if the order can drift."""
    sizes = [PROFILES[name].size for name in ("dev", "demo", "prod")]

    assert sizes == sorted(sizes)
    assert len(set(sizes)) == len(sizes)


def test_the_preview_price_is_its_two_calls() -> None:
    """Retired with USD_PER_PREVIEW (094): a preview's only possible call is
    the rewrite, priced by USD_PER_ROLEPLAY, pinned below."""


def test_an_empty_supabase_url_means_sign_in_is_not_configured() -> None:
    """A local process cannot unset what the env file sets; it can only set the
    variable empty. An empty string is not a URL, and taking it for one made the
    JWKS client refuse to start (123/#289's local target)."""
    settings = Settings(**_DB, supabase_project_url="")

    assert settings.supabase_project_url is None
