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

# Costs measured 2026-07-28 at USD_PER_VOTE below (docs/research/first-full-scale-run.md,
# superseding the 10-vote $0.000536 reading — output ran ~310 tokens/vote at scale,
# not 234):
#
#   dev   25 → $0.018/run — plumbing, where the verdict's content is irrelevant
#   demo 100 → $0.073/run — enough panelists to read as a panel
#   prod 200 → $0.145/run — ~70 fixed-length runs inside the $10 credit cap
#     (more in practice: a decisive pair stopped at 50 votes for $0.036)
#
# What each size *buys* is not recorded here: `verdict.detectable_gap` computes it from the
# size and the band, and every report carries it. A figure written down beside the table
# would silently outlive a change to either input.
#
# 200 keeps the size it was signed off at, but not the reason: it was chosen so that a
# `practical_tie` would be reachable, and a tie turns out to be reported on only ~5.6% of
# genuinely tied panels at that size. What defends it is the gap it can resolve.
PROFILES: dict[ProfileName, PanelProfile] = {
    "dev": PanelProfile(size=25, model="openai/gpt-5-mini"),
    "demo": PanelProfile(size=100, model="openai/gpt-5-mini"),
    "prod": PanelProfile(size=200, model="openai/gpt-5-mini"),
}

# The higher of the two at-scale readings ($0.000687 over 200 votes, $0.000726 over
# 50 — first-full-scale-run.md), so the pre-flight warning errs toward warning a run
# that would have squeaked through rather than waving through one that will not.
USD_PER_VOTE = 0.000726


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
    # Defaults to the cheapest profile on purpose: every size here is real money, so
    # forgetting to choose should cost a cent rather than a tenth of the credit cap.
    profile: ProfileName = "dev"
    targeting_model: str = "openai/gpt-5-mini"
    analyst_model: str = "openai/gpt-5-mini"
    embedding_model: str = "openai/text-embedding-3-small"
    judge_model: str = "openai/gpt-5-mini"

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
