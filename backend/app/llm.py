from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app.schemas import PanelVoteOutput, PlausibilityScore


VOTE_QUESTION = "Which do you prefer?"

# Held apart from the question so that varying the question (015) cannot reach the
# positional and content-based-reason instructions. A framing arm that reworded
# those would ablate framing and instruction-following together.
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
    ) -> None:
        # One test asks one question of everybody, so the question is panel
        # configuration rather than vote data. Binding it here keeps it off the
        # PanelLLM protocol, which every caller but 015 would carry for nothing.
        self._question = question
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
        messages = build_vote_messages(
            system_prompt, option_1, option_2, question=self._question
        )
        result = self._model.invoke(messages)
        if not isinstance(result, PanelVoteOutput):
            raise RuntimeError(f"panel model returned no structured vote: {result!r}")
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
