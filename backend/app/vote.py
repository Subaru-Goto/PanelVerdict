from typing import Literal, Protocol

from app.panel import render_persona_prompt
from app.schemas import PanelVoteOutput, Persona, VoteRecord


class PanelLLM(Protocol):
    def vote(
        self, *, system_prompt: str, option_1: str, option_2: str
    ) -> PanelVoteOutput: ...


def resolve_choice(
    chosen: Literal["option_1", "option_2"], presentation_order: list[str]
) -> str:
    """Map a positional pick back to the variant id it referred to.

    The model votes by position (option_1/option_2, identity-blind);
    presentation_order holds the variant_ids in the order this persona saw
    them. This re-attaches identity (002): option_1 -> the variant shown
    first, option_2 -> the variant shown second.
    """
    return presentation_order[0] if chosen == "option_1" else presentation_order[1]


def collect_panel_votes(
    *,
    test_id: str,
    variants: dict[str, str],
    panel: list[Persona],
    llm: PanelLLM,
) -> list[VoteRecord]:
    """Cast every persona's vote and return fully-identified records.

    Each persona sees the two variants in a counterbalanced order, votes
    positionally (blind to identity), and the position is resolved back to a
    variant_id. Aggregation (the verdict) is a separate step.
    """
    if len(variants) != 2:
        raise ValueError(
            f"collect_panel_votes requires exactly 2 variants, got {len(variants)}; "
            "multivariate (N-variant) is a v2 change (002 forward-compat)."
        )

    base = list(variants)
    records: list[VoteRecord] = []
    for index, persona in enumerate(panel):
        presentation_order = base if index % 2 == 0 else list(reversed(base))
        first_id, second_id = presentation_order
        output = llm.vote(
            system_prompt=render_persona_prompt(persona),
            option_1=variants[first_id],
            option_2=variants[second_id],
        )
        records.append(
            VoteRecord(
                persona_id=persona.id,
                test_id=test_id,
                chosen_variant_id=resolve_choice(output.chosen, presentation_order),
                presentation_order=presentation_order,
                reason=output.reason,
            )
        )
    return records
