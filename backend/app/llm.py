from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app.schemas import InterestSynthesis, PanelVoteOutput


def build_vote_messages(
    system_prompt: str, option_1: str, option_2: str
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
        "Which do you prefer? Pick option_1 or option_2, and give a one-line "
        "reason based on the content — not its position."
    )
    return [SystemMessage(content=system_prompt), HumanMessage(content=task)]


class OpenRouterPanelLLM:
    """PanelLLM backed by an OpenRouter chat model via LangChain.

    Config is injected so this module stays import-safe; wiring lives at the
    endpoint layer.
    """

    def __init__(self, *, api_key: str, base_url: str, model: str) -> None:
        # No temperature: gpt-5-mini (a reasoning model) rejects any non-default
        # temperature with a 400.
        self._model = ChatOpenAI(
            model=model,
            base_url=base_url,
            api_key=api_key,
        ).with_structured_output(PanelVoteOutput)

    def vote(
        self, *, system_prompt: str, option_1: str, option_2: str
    ) -> PanelVoteOutput:
        messages = build_vote_messages(system_prompt, option_1, option_2)
        result = self._model.invoke(messages)
        if not isinstance(result, PanelVoteOutput):
            raise RuntimeError(f"panel model returned no structured vote: {result!r}")
        return result


class OpenRouterInterestLLM:
    """InterestLLM backed by an OpenRouter chat model via LangChain."""

    def __init__(self, *, api_key: str, base_url: str, model: str) -> None:
        self._model = ChatOpenAI(
            model=model,
            base_url=base_url,
            api_key=api_key,
        ).with_structured_output(InterestSynthesis)

    def generate(self, *, prompt: str) -> InterestSynthesis:
        messages = [
            SystemMessage(
                content="You invent realistic, specific personal interests for "
                "synthetic survey personas."
            ),
            HumanMessage(content=prompt),
        ]
        result = self._model.invoke(messages)
        if not isinstance(result, InterestSynthesis):
            raise RuntimeError(f"interest model returned no structured list: {result!r}")
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
