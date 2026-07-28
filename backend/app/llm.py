import json
from time import perf_counter
from typing import Literal, get_args

import httpx
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from openai import APIStatusError

from app.schemas import (
    INCOME_BAND_QUINTILES,
    MAX_PERSONA_AGE,
    MIN_PERSONA_AGE,
    CultureTag,
    EducationLevel,
    Gender,
    Locale,
    PanelVoteOutput,
    PlausibilityScore,
    TargetRequest,
    TraitLevel,
    TraitName,
)
from app.vote import OutOfCredit, VoteResponse, VoteUsage


VOTE_QUESTION = "Which do you prefer?"

# OpenRouter's documented vocabulary for the GPT-5 series. Named as a closed set because
# an unrecognised effort is accepted by the request and then silently does nothing, which
# would read as "this effort makes no difference" rather than as a typo.
type ReasoningEffort = Literal[
    "none", "minimal", "low", "medium", "high", "xhigh", "max"
]

# Sourced from the first full-scale run (docs/research/first-full-scale-run.md):
# ~3× the slowest of 250 timed votes (18.9s) and ~4× their p99 (14.0s). Wide on
# purpose — cutting off a valid-but-slow reasoning response thins the panel, while
# a hang costs latency only; this caps a hung attempt at a minute instead of the
# SDK default's ten (the SDK may retry twice, so a persistently hanging vote costs
# at most ~three). Passed as the SDK's whole-request timeout — connect and write
# included — the read phase is just the part that ever ran long.
VOTE_READ_TIMEOUT_SECONDS = 60

# Held apart from the question so that varying the question cannot reach the
# positional and content-based-reason instructions. An experiment that reworded those
# would ablate the question and instruction-following together.
_ANSWER_INSTRUCTION = (
    "Pick option_1 or option_2, and give a one-line "
    "reason based on the content — not its position."
)


def build_vote_messages(
    system_prompt: str,
    option_1: str,
    option_2: str,
    *,
    question: str = VOTE_QUESTION,
) -> list[BaseMessage]:
    """Build the chat messages for one persona's vote.

    system = the persona prompt (who they are); human = the task, presenting
    the two options positionally (blind to identity) and asking for a
    content-based reason.
    """
    task = (
        "Here are two options.\n"
        f"Option 1: {option_1}\n"
        f"Option 2: {option_2}\n\n"
        f"{question} {_ANSWER_INSTRUCTION}"
    )
    return [SystemMessage(content=system_prompt), HumanMessage(content=task)]


def _listed(values: tuple[str, ...] | list[str]) -> str:
    return ", ".join(values)


# The vocabulary is read off the schema rather than typed out, so a country or trait
# level added there reaches the prompt with no edit here. A value the prompt omits is
# one the model cannot emit, which quietly makes that slice of the pool unreachable
# by any target description.
_TARGET_SYSTEM_PROMPT = f"""\
You translate a description of a target audience into a structured query over a \
pool of synthetic survey panelists.

A panelist carries exactly these attributes and nothing else:
- country: {_listed([locale.value for locale in Locale])}
- age: {MIN_PERSONA_AGE} to {MAX_PERSONA_AGE}
- gender: {_listed(get_args(Gender))}
- income, ranked within their own country: {_listed(tuple(INCOME_BAND_QUINTILES))}
- education: {_listed([level.value for level in EducationLevel])}
- Big Five personality — {_listed(get_args(TraitName))} — each at one of \
{_listed([level.value for level in TraitLevel])}

Rules:
1. Record every place the description mentions in `regions`, using the country's \
ISO 3166-1 alpha-2 code even when that country is not in the list above. Never \
substitute a country we have for one we do not. Always set `culture_tag` to the \
coarse bucket the place belongs to ({_listed([tag.value for tag in CultureTag])}) — \
it is what lets an unlisted country be approximated at all, so leave it null only \
when the place genuinely spans both buckets.
2. A place narrower than a country — a state, province, city or neighbourhood — \
goes in `regions` under its country AND in `unmapped`, because panelists carry no \
geography finer than a country and a panel drawn for the whole country is not the \
one that was asked for.
3. Read personality only from words about temperament or disposition, and put the \
words you read it from in `source_phrase`.
4. List in `unmapped`, verbatim, every part of the description that none of the \
attributes above can express — interests, hobbies, activities, occupations, brands, \
household composition, city, anything else. Do not approximate it with a personality \
trait or a demographic.
5. Leave a field empty rather than guessing.\
"""


def build_target_messages(description: str) -> list[BaseMessage]:
    """Build the chat messages that translate a target description into a query.

    The description is the human turn and nothing else, so target text cannot reach
    the instructions that constrain how it is read.
    """
    return [
        SystemMessage(content=_TARGET_SYSTEM_PROMPT),
        HumanMessage(content=description),
    ]


def _numeric(value: object) -> float | None:
    """A value out of the provider's own JSON, narrowed to a number or refused.

    `bool` is an `int` in Python, so it is excluded explicitly: a `true` where a cost was
    expected would otherwise total as 1.0 credit.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _vote_usage(raw: AIMessage, seconds: float) -> VoteUsage | None:
    """What one vote cost, read off the two places the numbers survive.

    The token counts come from `usage_metadata`, which langchain normalizes. `cost` comes
    from `response_metadata["token_usage"]`, the provider's dict passed through untouched
    — `UsageMetadata` has no cost field, so the bill reaches us only there. Reading both
    is deliberate, not redundancy.
    """
    usage = raw.usage_metadata
    if usage is None:
        return None
    token_usage = raw.response_metadata.get("token_usage")
    return VoteUsage(
        input_tokens=usage["input_tokens"],
        # Cached input bills at a reduced rate, so it is part of the cost. Expected to
        # read 0 for a vote: the providers' caches have a minimum prompt size several
        # times ours, so no prefix of ours is eligible (see prompt-caching.md).
        cached_tokens=usage.get("input_token_details", {}).get("cache_read"),
        output_tokens=usage["output_tokens"],
        # A provider that did not report reasoning leaves the key out rather than
        # writing a zero, and the difference is most of the bill.
        #
        # Both detail keys are read as literals, which holds only because no service tier
        # is requested: langchain builds them as f"{service_tier_prefix}reasoning" and
        # f"{service_tier_prefix}cache_read", so asking for `flex` or `priority` would
        # move them and silently return None for the largest cost term.
        reasoning_tokens=usage.get("output_token_details", {}).get("reasoning"),
        cost=_numeric(token_usage.get("cost"))
        if isinstance(token_usage, dict)
        else None,
        seconds=seconds,
    )


def _vote_response(result: dict[str, object], *, seconds: float) -> VoteResponse:
    """Turn `include_raw`'s three-key dict into a vote, or raise.

    `include_raw` stops a parse failure raising on its own — it arrives as
    `parsing_error` beside a null `parsed`. A caller that read only `parsed` would file
    the empty result as a real vote, so the raise `vote` already promised is restored
    here.

    Only the parse error's *type* is carried, never its message. langchain builds that
    message as `f"Invalid json output: {text}"`, so interpolating it would copy the model's
    entire reply into `VoteFailure.error` and from there into a log line. The type says
    which way the vote failed, which is what a caller does anything with; recovering the
    text costs a re-run, and that is the cheaper mistake.
    """
    error = result.get("parsing_error")
    if error is not None:
        raise RuntimeError(
            f"panel model returned no structured vote: {type(error).__name__}"
        )
    parsed = result.get("parsed")
    if not isinstance(parsed, PanelVoteOutput):
        raise RuntimeError(
            f"panel model returned no structured vote: {type(parsed).__name__}"
        )
    raw = result.get("raw")
    return VoteResponse(
        output=parsed,
        usage=_vote_usage(raw, seconds) if isinstance(raw, AIMessage) else None,
    )


class OpenRouterPanelLLM:
    """PanelLLM backed by an OpenRouter chat model via LangChain.

    Config is injected so this module stays import-safe; wiring lives at the
    endpoint layer.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        question: str = VOTE_QUESTION,
        reasoning_effort: ReasoningEffort | None = None,
    ) -> None:
        # One test asks one question of everybody, so the question is panel
        # configuration rather than vote data. Binding it here keeps it off the
        # PanelLLM protocol, which every caller but 015 would carry for nothing.
        # Reasoning effort is the same kind of thing: one panel deliberates one way, and
        # an experimental arm is a separate instance rather than a per-call argument.
        self._question = question
        # The whole ask, declared where it is bound: 015 showed the verdict moves
        # with the question's wording, so a vote cached under one question must not
        # answer another (010e). The scaffold is rendered by the real message
        # builder with blank inputs — the blanks are what the fingerprint itself
        # carries — so an edit to the template or the answer instruction changes
        # this string without anyone remembering to mirror it here. JSON framing
        # for the same reason as the fingerprint's: the question is free text.
        scaffold = build_vote_messages("", "", "", question=question)
        self.configuration = json.dumps(
            {
                "model": model,
                "effort": reasoning_effort,
                "ask": [str(message.content) for message in scaffold],
            }
        )
        # No temperature: gpt-5-mini (a reasoning model) rejects any non-default
        # temperature with a 400.
        #
        # `max_retries` is the SDK's own default, stated rather than inherited: a panel
        # fans 25 requests out at once, so 429s are expected traffic and this is the line
        # that decides whether one costs a vote. The SDK backs off and honours
        # `retry-after`. The read timeout waited for a measured latency distribution
        # rather than being guessed; it has one now — see VOTE_READ_TIMEOUT_SECONDS.
        # `include_raw` keeps the AIMessage, which is the only way to reach what the
        # vote cost: the parsed-object form discards it. It rewires the output plumbing
        # and nothing else — the bound model is identical — so it cannot move a prompt
        # token, which is what keeps votes already collected comparable with votes cast
        # after it.
        #
        # `reasoning_effort` and not the `reasoning={"effort": ...}` object the provider
        # documents, because setting `reasoning` is one of the conditions that switches
        # langchain to the **Responses API** — a different endpoint, whose response
        # carries no `token_usage` and therefore no `cost`, and which nothing measured
        # here has ever been taken against. Confirmed on the wire: the object form comes
        # back with Responses-shaped metadata and the cost missing, while this form stays
        # on Chat Completions and reports it. Forcing `use_responses_api=False` alongside
        # the object is not a way out — the request is then rejected outright.
        #
        # Left unset by default, so the default arm is the provider's own default effort.
        self._model = ChatOpenAI(
            model=model,
            base_url=base_url,
            api_key=api_key,
            max_retries=2,
            timeout=VOTE_READ_TIMEOUT_SECONDS,
            reasoning_effort=reasoning_effort,
        ).with_structured_output(PanelVoteOutput, include_raw=True)

    def vote(self, *, system_prompt: str, option_1: str, option_2: str) -> VoteResponse:
        messages = build_vote_messages(
            system_prompt, option_1, option_2, question=self._question
        )
        started = perf_counter()
        try:
            result = self._model.invoke(messages)
        except APIStatusError as error:
            # The SDK retries 429/5xx itself; a 402 arrives here directly and is
            # terminal for the whole run, not just this vote. Fixed text only —
            # the provider's message never travels.
            if error.status_code == 402:
                raise OutOfCredit("OpenRouter credit exhausted (402)") from error
            raise
        seconds = perf_counter() - started
        if not isinstance(result, dict):
            raise RuntimeError(
                f"expected include_raw's dict, got {type(result).__name__}"
            )
        return _vote_response(result, seconds=seconds)


def remaining_credit(*, api_key: str, base_url: str) -> float | None:
    """What is left on the key (`GET /key`, same units as the vote costs), or None
    when unknown — an unlimited key reports null, and a failed check reports
    nothing: the pre-flight is advisory, and a broken meter must never block or
    misprice a run it cannot read.
    """
    try:
        response = httpx.get(
            f"{base_url}/key",
            headers={"Authorization": f"Bearer {api_key}"},
            # Not a measured figure like the vote timeout — there is nothing to
            # measure: the check is advisory, any failure (including this timeout)
            # returns None, and 5s only bounds how long the pre-flight may delay
            # the run it advises.
            timeout=5,
        )
        response.raise_for_status()
        remaining = response.json()["data"]["limit_remaining"]
        return float(remaining) if remaining is not None else None
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        return None


class OpenRouterTargetTranslator:
    """TargetTranslator backed by an OpenRouter chat model via LangChain.

    A `TargetRequest` and not a `TargetQuery`: the model reads the description, and
    code alone decides what the pool can serve for it. Handing the model the
    coverage ladder would put the substitutions where nothing can attach a notice
    to them.
    """

    def __init__(self, *, api_key: str, base_url: str, model: str) -> None:
        self._model = ChatOpenAI(
            model=model,
            base_url=base_url,
            api_key=api_key,
        ).with_structured_output(TargetRequest)

    def translate(self, *, description: str) -> TargetRequest:
        result = self._model.invoke(build_target_messages(description))
        if not isinstance(result, TargetRequest):
            raise RuntimeError(f"translator returned no structured target: {result!r}")
        return result


class OpenRouterEmbedder:
    """Embedder backed by OpenRouter's embeddings endpoint via LangChain."""

    def __init__(self, *, api_key: str, base_url: str, model: str) -> None:
        self._embeddings = OpenAIEmbeddings(
            model=model,
            base_url=base_url,
            api_key=api_key,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._embeddings.embed_documents(texts)


class OpenRouterJudge:
    """Judge backed by an OpenRouter chat model via LangChain (006e G-Eval)."""

    def __init__(self, *, api_key: str, base_url: str, model: str) -> None:
        self._model = ChatOpenAI(
            model=model,
            base_url=base_url,
            api_key=api_key,
        ).with_structured_output(PlausibilityScore)

    def score(self, *, prompt: str) -> PlausibilityScore:
        messages = [
            SystemMessage(
                content="You are a careful evaluator of synthetic survey personas."
            ),
            HumanMessage(content=prompt),
        ]
        result = self._model.invoke(messages)
        if not isinstance(result, PlausibilityScore):
            raise RuntimeError(f"judge returned no structured score: {result!r}")
        return result
