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

# Per-run costs at the MEASURED Luna rate (see USD_PER_VOTE; guard thresholds use its
# 0.00015 margin figure, real spend runs ~$0.0001212/vote):
#
#   dev   25 → ~$0.003/run measured (guard warns below $0.00375)
#   demo 100 → ~$0.012/run measured (guard warns below $0.015)
#   prod 200 → ~$0.024/run measured (guard warns below $0.030) — ~400 fixed-length runs
#              inside the $10 credit cap
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

# MEASURED 2026-08-23, with a stated margin. The 20-vote `vote_cost` probe on
# openai/gpt-5.6-luna reported $0.0001212/vote (provider `cost` field, 10/10 default-arm
# votes — the method 010a validated bit-for-bit against list-price derivation), and the
# 5,400-vote 071 gate run derived to ~$0.65 total, consistent with the account dashboard.
# Full numbers: docs/research/manipulation-check-luna.md.
#
# - Rounded UP to 0.00015 — a 1.24x allowance on the measurement, because this constant is
#   `budget_notice`'s pre-flight threshold and the conservative error for a guard is high.
#   The probe's variance argues the same way: p95 output ran ~1.5x the mean.
# - Probe prompts (~352 tokens) sit inside the prod vote's measured 270–370 range, so the
#   per-vote figure transfers to real panels.
# - This replaces the 0.0003 list-price estimate of 2026-08-05, which proved ~2.5x high —
#   Luna emits ~6.5 reasoning tokens/vote where gpt-5-mini emitted ~160, and reasoning was
#   the term the old margin existed to absorb.
USD_PER_VOTE = 0.00015


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
