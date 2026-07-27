import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.messages.ai import (
    InputTokenDetails,
    OutputTokenDetails,
    UsageMetadata,
)

from langchain_openai import ChatOpenAI

from app.llm import OpenRouterPanelLLM, _vote_response, build_vote_messages
from app.schemas import PanelVoteOutput

# 014's 5,400 collected votes were cast under exactly this task text. Pinning it as
# a literal is what makes a later edit visible rather than quietly making that run
# incomparable to everything after it.
_ANSWER_INSTRUCTION = (
    "Pick option_1 or option_2, and give a one-line "
    "reason based on the content — not its position."
)
_DEFAULT_TASK = (
    "Here are two options.\nOption 1: A\nOption 2: B\n\n"
    f"Which do you prefer? {_ANSWER_INSTRUCTION}"
)


def test_the_shipped_task_text_is_unchanged() -> None:
    messages = build_vote_messages(system_prompt="s", option_1="A", option_2="B")
    assert messages[1].content == _DEFAULT_TASK


def test_a_custom_question_cannot_reach_the_answer_instruction() -> None:
    """015 varies the question sentence and nothing else.

    The positional and content-based-reason instructions are outside the
    parameter, so an experimental arm cannot reword them even by accident —
    otherwise the framing ablation would ablate instruction-following with it.
    """
    messages = build_vote_messages(
        system_prompt="s",
        option_1="A",
        option_2="B",
        question="Which would you be more likely to click?",
    )
    content = messages[1].content

    assert "Which would you be more likely to click?" in content
    assert "Which do you prefer?" not in content
    assert content.endswith(_ANSWER_INSTRUCTION)


def test_build_vote_messages_puts_persona_in_system_and_options_in_order() -> None:
    messages = build_vote_messages(
        system_prompt="You are a 30-year-old.",
        option_1="Save 50% today",
        option_2="Limited time: half price",
    )

    assert len(messages) == 2
    system, human = messages

    # persona goes in the system message, verbatim
    assert isinstance(system, SystemMessage)
    assert system.content == "You are a 30-year-old."

    # the task goes in the human message: both option texts present, and
    # option_1's text appears before option_2's (slot order preserved).
    assert isinstance(human, HumanMessage)
    assert human.content.index("Save 50% today") < human.content.index(
        "Limited time: half price"
    )


def _raw(
    *,
    input_tokens: int = 300,
    output_tokens: int = 80,
    output_token_details: dict[str, int] | None = None,
    token_usage: dict[str, object] | None = None,
) -> AIMessage:
    """An AIMessage shaped the way langchain hands one back from a vote.

    `usage_metadata` is langchain's normalized view; `response_metadata["token_usage"]`
    is the provider's own dict passed through untouched. The two carry different fields,
    which is the whole reason both are read.
    """
    return AIMessage(
        content='{"chosen": "option_1", "reason": "stub"}',
        usage_metadata=UsageMetadata(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            input_token_details=InputTokenDetails(),
            output_token_details=OutputTokenDetails(**(output_token_details or {})),
        ),
        response_metadata={"token_usage": token_usage} if token_usage else {},
    )


def _result(raw: AIMessage, parsed: PanelVoteOutput | None = None) -> dict[str, object]:
    return {
        "raw": raw,
        "parsed": parsed or PanelVoteOutput(chosen="option_1", reason="stub"),
        "parsing_error": None,
    }


def test_reasoning_tokens_absent_means_unreported_not_zero() -> None:
    """langchain drops the key rather than writing a zero, so a provider that reports
    no reasoning is indistinguishable from one that reasoned for free unless the
    absence survives as None. Reasoning bills at the output rate and is the largest
    single term, so a zero here understates the bill by most of it."""
    response = _vote_response(_result(_raw(output_token_details={})), seconds=1.0)

    assert response.usage is not None
    assert response.usage.reasoning_tokens is None


def test_reasoning_tokens_are_carried_when_the_provider_reports_them() -> None:
    response = _vote_response(
        _result(_raw(output_token_details={"reasoning": 192})), seconds=1.0
    )

    assert response.usage is not None
    assert response.usage.reasoning_tokens == 192


def test_cost_is_read_from_the_provider_dict_that_usage_metadata_discards() -> None:
    """OpenRouter reports what the request actually cost. UsageMetadata has no field
    for it, so it survives only on response_metadata["token_usage"] — which means the
    bill and the token counts come from two different places on the same message."""
    response = _vote_response(
        _result(_raw(token_usage={"cost": 0.00021, "prompt_tokens": 300})), seconds=1.0
    )

    assert response.usage is not None
    assert response.usage.cost == 0.00021
    assert response.usage.input_tokens == 300


def test_a_missing_cost_is_none_rather_than_free() -> None:
    response = _vote_response(_result(_raw()), seconds=1.0)

    assert response.usage is not None
    assert response.usage.cost is None


def test_a_cost_that_is_not_a_number_is_refused() -> None:
    """The provider dict is untyped JSON. A string where a number was expected must
    not become part of a total that a budget decision reads."""
    response = _vote_response(
        _result(_raw(token_usage={"cost": "0.00021"})), seconds=1.0
    )

    assert response.usage is not None
    assert response.usage.cost is None


def test_a_response_with_no_usage_at_all_reports_none() -> None:
    """langchain only attaches usage_metadata when the provider sent a usage block, so
    the vote still has to come back — with the cost unknown rather than zero."""
    raw = AIMessage(content='{"chosen": "option_1", "reason": "stub"}')

    response = _vote_response(_result(raw), seconds=1.0)

    assert response.output.chosen == "option_1"
    assert response.usage is None


def test_the_observed_latency_travels_with_the_vote() -> None:
    response = _vote_response(_result(_raw()), seconds=4.65)

    assert response.usage is not None
    assert response.usage.seconds == 4.65


def test_a_parsing_error_raises_and_names_the_failure() -> None:
    """include_raw stops a parse failure raising on its own — it comes back in the
    dict. A caller that only checked `parsed` would file an empty vote as a real one,
    so this is converted back into the raise `vote` already promised, carrying the
    reason rather than a dump of the whole message."""
    raw = AIMessage(content="not json at all")
    result = {"raw": raw, "parsed": None, "parsing_error": ValueError("bad json")}

    with pytest.raises(RuntimeError) as caught:
        _vote_response(result, seconds=1.0)

    assert "bad json" in str(caught.value)
    assert "not json at all" not in str(caught.value)


def test_cached_input_tokens_are_carried_when_reported() -> None:
    """prompt-caching.md concluded a cache cannot fire at our prompt size, from published
    thresholds rather than observation. Carrying the figure is what lets a real run either
    confirm that or overturn it — and cached input bills at a reduced rate regardless."""
    raw = _raw()
    raw.usage_metadata["input_token_details"]["cache_read"] = 0

    response = _vote_response(_result(raw), seconds=1.0)

    assert response.usage is not None
    assert response.usage.cached_tokens == 0


def test_no_cache_figure_is_unreported_rather_than_zero() -> None:
    response = _vote_response(_result(_raw()), seconds=1.0)

    assert response.usage is not None
    assert response.usage.cached_tokens is None


def _bound_model(llm: OpenRouterPanelLLM) -> ChatOpenAI:
    """The chat model inside include_raw's runnable: RunnableMap(raw=llm) | parser."""
    return llm._model.steps[0].steps__["raw"]


def test_a_reasoning_effort_is_sent_as_the_unified_object() -> None:
    """The trap this guards is that an unrecognised or misnamed reasoning parameter is
    accepted and then does nothing, so an arm measuring `low` would return the default's
    numbers and read as "effort makes no difference" rather than as a wiring bug. It
    reaches through the runnable because the only other way to notice is a paid call.

    `reasoning` and not `reasoning_effort`: both are passed through verbatim on the Chat
    Completions path, and OpenRouter documents only the former.
    """
    llm = OpenRouterPanelLLM(
        api_key="test",
        base_url="http://openrouter.invalid",
        model="openai/gpt-5-mini",
        reasoning_effort="low",
    )

    assert _bound_model(llm)._default_params["reasoning"] == {"effort": "low"}


def test_the_default_arm_sends_no_reasoning_parameter_at_all() -> None:
    """Every measurement this project has was taken at the provider's default effort, so
    the default has to stay untouched rather than become an explicit medium."""
    llm = OpenRouterPanelLLM(
        api_key="test", base_url="http://openrouter.invalid", model="openai/gpt-5-mini"
    )

    assert _bound_model(llm).reasoning is None
