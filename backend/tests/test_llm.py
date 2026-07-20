from langchain_core.messages import HumanMessage, SystemMessage

from app.llm import build_vote_messages


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
