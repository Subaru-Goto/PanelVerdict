from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage


def build_vote_messages(
    system_prompt: str, option_1: str, option_2: str
) -> list[BaseMessage]:
    """Assemble the chat messages for one persona's vote.

    system = the persona prompt (who they are); human = the task: the two
    options presented positionally (identity-blind) with a request for a
    content-based reason (002). Pure and network-free, so it is unit-testable
    without calling a model.
    """
    task = (
        "Here are two options.\n"
        f"Option 1: {option_1}\n"
        f"Option 2: {option_2}\n\n"
        "Which do you prefer? Pick option_1 or option_2, and give a one-line "
        "reason based on the content — not its position."
    )
    return [SystemMessage(content=system_prompt), HumanMessage(content=task)]
