from langchain_core.messages import HumanMessage, SystemMessage

from app.llm import build_vote_messages

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
