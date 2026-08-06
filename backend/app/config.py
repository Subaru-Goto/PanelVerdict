from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# parents[2]: app/ -> backend/ -> repo root, where the shared credentials file lives
ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"


@dataclass(frozen=True)
class PanelProfile:
    """What one run of the panel is sized and priced to be.

    A panel size is not a tuning knob, it is a purchase: 200 votes cost 200 model calls,
    and the resolution it buys improves only as the square root. So the size travels with
    the model it will be spent on, and the choice is made once per environment rather than
    per call site.
    """

    size: int
    model: str


type ProfileName = Literal["dev", "demo", "prod"]

# Per-run costs, ESTIMATED for Luna rather than measured — see USD_PER_VOTE:
#
#   dev   25 → ~$0.008/run — plumbing, where the verdict's content is irrelevant
#   demo 100 → ~$0.030/run — enough panelists to read as a panel
#   prod 200 → ~$0.060/run — ~166 fixed-length runs inside the $10 credit cap
#
# The measured gpt-5-mini figures these replace, kept for comparison: $0.018 / $0.073 /
# $0.145, with a decisive pair stopping at 50 votes for $0.036.
#
# What each size *buys* is not recorded here: `verdict.detectable_gap` computes it from the
# size and the band, and every report carries it. A figure written down beside the table
# would silently outlive a change to either input.
#
# 200 keeps the size it was signed off at, but not the reason: it was chosen so that a
# `practical_tie` would be reachable, and a tie turns out to be reported on only ~5.6% of
# genuinely tied panels at that size. What defends it is the gap it can resolve.
PROFILES: dict[ProfileName, PanelProfile] = {
    "dev": PanelProfile(size=25, model="openai/gpt-5.6-luna"),
    "demo": PanelProfile(size=100, model="openai/gpt-5.6-luna"),
    "prod": PanelProfile(size=200, model="openai/gpt-5.6-luna"),
}

# ESTIMATED, not measured. Signed off 2026-08-05: test budget belongs to development, so
# this is derived from list prices instead of bought.
#
# - The method is validated against the one figure we did measure: 270 input + 310 output
#   tokens/vote at gpt-5-mini's $0.25/$2.00 per Mtok derives $0.0006875 against a measured
#   $0.000687 (first-full-scale-run.md) — agreement to within a rounding step, not exact.
#   So the arithmetic is sound and only the token counts are uncertain on a new model.
# - Same token counts at Luna's $0.10/$0.60 (OpenRouter model list, read 2026-08-05) give
#   **$0.000213/vote** — 31% of gpt-5-mini.
# - Rounded UP to 0.0003: a 1.41x allowance on the total, because a different model emits a
#   different amount of reasoning and that term dominates. (Applied to the output term
#   alone it would be 1.47x; the margin is stated against the total, which is what
#   `budget_notice` multiplies.)
# - The round number is deliberate. A figure like 0.000287 would read as measured.
#
# HOW THIS WEAKENS THE PRE-FLIGHT WARNING, stated because the number went DOWN. This
# constant is the threshold in `budget_notice`, so a prod run now warns below $0.060 where
# it warned below $0.145 — a guard ~2.4x looser than anything previously shipped. That is
# correct if the estimate is right and under-warns if Luna reasons more than gpt-5-mini did.
# The 1.41x margin is the whole defence, which is why it errs high against the *derivation*
# rather than against the retired constant.
#
# Replace with a measured value the first time a paid run is made on Luna
# (issues/071-the-panel-model-changed-without-its-gate.md).
USD_PER_VOTE = 0.0003


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_ENV, extra="ignore")

    postgres_user: str
    postgres_password: str
    postgres_db: str
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    frontend_origin: str = "http://localhost:3000"
    openrouter_api_key: SecretStr | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    model_provider: str = "openai"
    profile: ProfileName = "dev"
    # Plain Luna, not `-pro`: `TARGET_REASONING_EFFORT = "low"` is a measured setting
    # (targeting-call-effort.md), and `-pro` is the same model served with reasoning mode
    # fixed at `pro` — so the effort argument may be ignored while output pushes toward
    # TARGET_MAX_COMPLETION_TOKENS, which is the interaction that doc exists to prevent.
    targeting_model: str = "openai/gpt-5.6-luna"
    # Plain Luna for latency, not cost: this one streams to a reader, so time-to-first-token
    # is felt where the panel's is not. `-pro` emits more reasoning before it answers.
    analyst_model: str = "openai/gpt-5.6-luna"
    embedding_model: str = "openai/text-embedding-3-small"
    # `-pro` on both below, and the reason is the same: one call per run, so the extra
    # reasoning tokens cost almost nothing in absolute terms, and both are judgements where
    # being wrong is expensive — a screener that misses an injection, a judge that scores a
    # bad answer well. Neither is bounded by an output cap, so unlike `targeting_model`
    # there is no ceiling for `pro` mode to collide with.
    # NOT yet validated: 071 records that `-pro` changes model behaviour and needs the same
    # scrutiny as any other model change. These two are the cheapest places to be wrong.
    judge_model: str = "openai/gpt-5.6-luna-pro"
    screening_model: str = "openai/gpt-5.6-luna-pro"

    @property
    def panel(self) -> PanelProfile:
        return PROFILES[self.profile]

    @property
    def database_url(self) -> str:
        return str(
            PostgresDsn.build(
                scheme="postgresql",
                username=self.postgres_user,
                password=self.postgres_password,
                host=self.postgres_host,
                port=self.postgres_port,
                path=self.postgres_db,
            )
        )


settings = Settings()
