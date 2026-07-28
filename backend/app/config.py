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

# Costs measured 2026-07-28 at $0.000536/vote (docs/research/panel-model-selection.md);
# nothing derives them, so they are recorded here.
#
#   dev   25 → $0.013/run — plumbing, where the verdict's content is irrelevant
#   demo 100 → $0.054/run — enough panelists to read as a panel
#   prod 200 → $0.107/run — ~93 runs inside the $10 credit cap
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
