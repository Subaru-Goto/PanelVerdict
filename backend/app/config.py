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
# 0.0002 margin figure, real spend runs ~$0.00015–0.00017/vote per the dashboard-
# reconciled gate run):
#
#   dev   25 → ~$0.004/run measured (guard warns below $0.005)
#   demo 100 → ~$0.016/run measured (guard warns below $0.020)
#   prod 200 → ~$0.032/run measured (guard warns below $0.040) — ~300 fixed-length runs
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

# MEASURED 2026-08-23, twice — and the bigger sample won. The 20-vote `vote_cost` probe
# on openai/gpt-5.6-luna reported $0.0001212/vote (provider `cost` field, 010a's method).
# The 5,400-vote 071 gate run then landed at **€0.79 for the day** on the author's
# dashboard (2026-08-23, key serving only this project that day) — ~$0.83–0.92 across
# plausible EUR/USD rates, possibly inflated by card FX if read from a bank view — which
# derives to **~$0.00015–0.00017/vote**. The probe's 10 default-arm votes under-sampled a
# population whose trait-rendered prompts run longer.
# Full numbers: docs/research/manipulation-check-luna.md.
#
# - Rounded UP to 0.0002 — a ~1.2–1.3x allowance over that range. Thinner than the old
#   1.41x philosophy and accepted deliberately: this constant only gates a warn-and-
#   proceed notice, and the next dashboard-reconciled paid run should tighten the range
#   (read the figure from OpenRouter's own USD activity view, not a converted card view).
# - A first pass set 0.00015 from the probe alone and the same day's dashboard erased the
#   margin — a sample-of-10 is a probe, not a measurement.
# - This replaces the 0.0003 list-price estimate of 2026-08-05, which proved ~2x high —
#   Luna emits ~6.5 reasoning tokens/vote where gpt-5-mini emitted ~160, and reasoning was
#   the term the old margin existed to absorb.
USD_PER_VOTE = 0.0002

# What one chat turn charges the day's pool (064/#192). 064 signs off a turn as
# "a fraction of a vote" and records the analyst's own cost as unmeasured, so
# the pool rounds that fraction up to the one price that IS measured. Replace
# with a measured per-turn figure when one exists (064's open question).
USD_PER_TURN = USD_PER_VOTE


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_ENV, extra="ignore")

    postgres_user: str
    postgres_password: str
    postgres_db: str
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    frontend_origin: str = "http://localhost:3000"
    # The edge secret the frontend's server-side proxy sends with every call to
    # a paid endpoint (045/#143). Never NEXT_PUBLIC_*: anything compiled into
    # the browser bundle authenticates nobody. None = guard off, for local dev
    # and CI; the deploy sets it.
    api_shared_secret: SecretStr | None = None
    # Derived, not tuned (045/#143): a prod run is 200 votes × USD_PER_VOTE
    # ($0.0002, dashboard-reconciled — see 071) = $0.04, so 25 runs bounds one
    # caller's worst-case spend at $1.00 per day. Raise it by deciding a new
    # ceiling, not by feel.
    evaluate_runs_per_day: int = 25
    # Bounded by structure, not price — honestly flagged: no per-turn dollar
    # measurement exists yet (unlike USD_PER_VOTE). A turn is at most 4 model
    # calls (analyst.py's recursion budget), a thread is one report's
    # conversation, and 30 turns/day is far above an honest conversation while
    # still bounding a loop. Replace with a derived ceiling once a turn's cost
    # is measured from the usage logs.
    chat_turns_per_thread_per_day: int = 30
    # The thread cap bounds one runaway conversation; this one bounds the
    # caller, because the client mints thread ids and could otherwise reset the
    # thread cap at will. Deliberately looser than the thread cap is tight: an
    # honest visitor may open several reports in a session.
    chat_turns_per_caller_per_day: int = 120
    # 064's load-bearing layer: the caps above bound one caller, but a new
    # caller costs nothing to mint, so only a global pool bounds what a day can
    # cost. $1.00 is the author's signed-off ceiling ("no more than 1 euro a
    # day"), expressed in USD deliberately unconverted — 064 records why a
    # hardcoded FX rate would be worse than a cent of drift. 0 disables, the
    # same escape hatch the other caps have.
    global_daily_cap_usd: float = 1.00
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
    # Plain Luna here too (2026-08-23, was `-pro`): OpenRouter routes each request only to
    # providers compatible with the account's data policy, and `-pro`'s provider set can
    # fall entirely outside it — the failure is a 404 ("no endpoints available matching
    # your guardrail restrictions") on every screen and judge call, which takes down every
    # evaluate run. `-pro` was also never validated in these roles (071: `-pro` changes
    # model behaviour and needs the same scrutiny as any other model change), while plain
    # Luna is the one model that passed its gate. If `-pro` returns, it needs both the
    # privacy settings loosened and its own validation pass.
    judge_model: str = "openai/gpt-5.6-luna"
    screening_model: str = "openai/gpt-5.6-luna"

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
