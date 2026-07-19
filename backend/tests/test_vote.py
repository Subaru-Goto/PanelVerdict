from typing import Literal

import pytest

from app.vote import resolve_choice


@pytest.mark.parametrize(
    ("chosen", "presentation_order", "expected"),
    [
        # Same order shown: option_1 is first, option_2 is second.
        ("option_1", ["vA", "vB"], "vA"),
        ("option_2", ["vA", "vB"], "vB"),
        # Swapped order (the case counterbalancing creates): the SLOT still
        # maps by position, so option_1 now refers to vB.
        ("option_1", ["vB", "vA"], "vB"),
        ("option_2", ["vB", "vA"], "vA"),
    ],
)
def test_resolve_choice(
    chosen: Literal["option_1", "option_2"],
    presentation_order: list[str],
    expected: str,
) -> None:
    assert resolve_choice(chosen, presentation_order) == expected
