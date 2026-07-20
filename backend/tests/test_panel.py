import pytest

from app.panel import _join_with_and


@pytest.mark.parametrize(
    ("items", "expected"),
    [
        (["solo"], "solo"),
        (["a", "b"], "a and b"),
        (["a", "b", "c"], "a, b and c"),
        (["a", "b", "c", "d"], "a, b, c and d"),
    ],
)
def test_join_with_and(items: list[str], expected: str) -> None:
    assert _join_with_and(items) == expected


def test_join_with_and_empty_raises() -> None:
    with pytest.raises(IndexError):
        _join_with_and([])
