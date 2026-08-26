from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# parents[2]: app/ -> backend/ -> repo root, where the shared credentials file lives
ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"


# Which LangChain integration builds the client — NOT which vendor serves the model.
# It is "openai" because OpenRouter speaks the OpenAI wire protocol for everything it
# routes to, so an Anthropic or Google model reached through OpenRouter is still built
# by `langchain-openai`. Verified 2026-08-26: `init_chat_model("anthropic/claude-haiku-4.5",
# model_provider="openai", base_url=<openrouter>)` returns a ChatOpenAI and OpenRouter
# reports serving `anthropic/claude-haiku-4.5`.
#
# A module constant rather than a `Settings` field (036 made it one, and
# tech-debt/#171 recorded the clump it created): it is a property of the endpoint this
# app talks to, not of the model, so it is not the thing anyone changes to swap a model.
# Swapping a model is one string — `targeting_model`, `analyst_model`, `judge_model`,
# `screening_model`, or the profile's — and this stays put. If a future endpoint does not
# speak the OpenAI protocol, that is one constant here and a new client, not a field
# threaded through every call site. It lives here rather than in `llm.py` so that
# `screening.py` does not have to import the vote path to reach one word.
LANGCHAIN_INTEGRATION = "openai"


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

# An upper bound, not a measurement of the model in use: measured 2026-07-31 on
# `openai/gpt-5-mini` at `TARGET_REASONING_EFFORT = "low"`, a $0.00061-$0.00111
# band across five descriptions (docs/research/targeting-call-effort.md). The
# translator runs on Luna, where mini-derived pricing proved ~2x high for votes,
# so this over-states the cost — the safe direction for a ceiling.
USD_PER_TRANSLATION = 0.0012

# What a preview costs the pool: the two model calls a run makes before the gate,
# one translation and one screening. Written as a figure rather than a sum
# because `_usd` takes written figures only; test_config pins it to its parts.
# The screening half is priced at USD_PER_VOTE, the one measured single-call
# figure here. Headline screening is not in it — that sits behind the gate.
USD_PER_PREVIEW = 0.0014

# What one rewrite charges the day's pool: the audience words turned into one
# panelist instruction, plus the classification that rides the same call.
#
# The translator's figure, not a new one, because it is the translator's call —
# same model, same `TARGET_MAX_COMPLETION_TOKENS`, same `TARGET_REASONING_EFFORT`,
# reading the same field. 016/#123's subject changed job rather than vanishing,
# and an upper bound measured on the harder version of a task is still an upper
# bound on the easier one.
#
# Charged only when the reader wrote audience words: blank calls nothing, which
# is likely the common case (094/#200).
USD_PER_ROLEPLAY = USD_PER_TRANSLATION

# What one chat turn charges the day's pool (064/#192). 064 calls a turn "a
# fraction of a vote" but leaves the analyst's own cost unmeasured, so the pool
# rounds up to the one price that is measured. Replace once a turn is measured.
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
    # Derived, not tuned (045/#143, cut to 3 by 092/#197): a prod run is 200
    # votes × USD_PER_VOTE ($0.0002, dashboard-reconciled — see 071) = $0.04,
    # so GLOBAL_DAILY_CAP_USD of $1.00 buys ~25 prod runs for the whole day.
    # 25 per caller was therefore the entire day's pool handed to one person —
    # a personal limit sitting at the global ceiling bounds nobody. At 3 the
    # day serves ~8 distinct people before the pool decides. (092 reached the
    # same conclusion from a ~$0.060/run figure; this comment derives it from
    # the constants in this file instead, and the conclusion is the same.)
    #
    # This became enforceable only with 063/#158: a limit per *caller* means
    # something once the caller is a verified subject id rather than a
    # forwarded address, since an address costs nothing to change.
    evaluate_runs_per_day: int = 3
    # Previews are not purchases, so they get their own, looser cap. Derived
    # against the prod panel the deploy runs: 25 x USD_PER_PREVIEW = $0.035,
    # under the $0.04 of one panel (200 x USD_PER_VOTE) this caller may buy. So
    # a whole allowance spent looking still costs the day less than one run, and
    # 25 is ~8 previews per purchasable panel. 0 disables.
    evaluate_previews_per_day: int = 25
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
    # The caps above bound one caller, but a caller costs nothing to mint, so
    # only a global pool bounds what a day can cost (064). $1.00 is the
    # signed-off ceiling ("no more than 1 euro a day"), left unconverted —
    # 064 records why a hardcoded FX rate is worse than a cent of drift.
    # 0 disables, as above.
    global_daily_cap_usd: float = 1.00
    # The Supabase project sign-in runs against, e.g. https://<ref>.supabase.co
    # (063/#158). None = sign-in not configured, and `caller_id` then falls back
    # to the pre-auth identity — the same escape hatch api_shared_secret uses,
    # so local development and CI need no auth project. The deploy sets it.
    # Public by nature: it is the host the browser talks to, not a credential.
    supabase_project_url: str | None = None
    # Elevated key, backend only, used for exactly one thing: asking Supabase to
    # delete a user who asked to be deleted. It bypasses Row Level Security
    # ("full access to your project's data" — guides/api/api-keys, read
    # 2026-08-24), so it never reaches the browser and nothing else may use it.
    # None = the deletion endpoint reports itself unavailable rather than
    # pretending to have deleted an account.
    supabase_service_key: SecretStr | None = None
    openrouter_api_key: SecretStr | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    profile: ProfileName = "dev"
    # Plain Luna, not `-pro`: `TARGET_REASONING_EFFORT = "low"` is a measured setting
    # (targeting-call-effort.md), and `-pro` is the same model served with reasoning mode
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

    # Declared here, not left to the SDK, because `/health` and the form's
    # disclosure line need to know whether tracing is on. `app.tracing` exports
    # them.
    langsmith_tracing: bool = False
    # None = tracing stays off however the flag is set. A tracer with no key
    # fails on every model call and sends nothing, so it is worse than off.
    langsmith_api_key: SecretStr | None = None
    langsmith_project: str = "panel-verdict"
    # The EU host: a key issued in one LangSmith region is not valid at the
    # other, so the SDK's US default would 403 this project's key.
    langsmith_endpoint: str = "https://eu.api.smith.langchain.com"

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
