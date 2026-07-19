from typing import Literal


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
