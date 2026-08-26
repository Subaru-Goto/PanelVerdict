from app.corpus import split_document

_DOC = """# What the tie zone is

A band of differences too small to act on.

## Why a product takes a stance

Somebody has to say how small is too small, and the answer is a judgement.

## Why the whole range must clear it

Leaning past the band is not clearing it.
"""


def test_each_heading_becomes_its_own_chunk() -> None:
    """The heading is the unit because it is the unit of *meaning*: a claim and
    the caveat that qualifies it are written under one heading, so a chunk that
    splits them can retrieve the confident half alone.

    The opening paragraph is a chunk too, under the title — it is where a
    document says the thing it is about, and dropping it would lose the plainest
    answer in the corpus.
    """
    chunks = split_document(_DOC)

    assert [chunk.section for chunk in chunks] == [
        "What the tie zone is",
        "Why a product takes a stance",
        "Why the whole range must clear it",
    ]
    assert all(chunk.source == "What the tie zone is" for chunk in chunks)
    assert chunks[0].text == "A band of differences too small to act on."


def test_a_chunk_is_searched_under_its_own_heading() -> None:
    """Readers ask in the words of a heading — "why is this not decisive" — and
    the body under it often never repeats them. Embedding and keyword-matching
    the body alone loses the one line written to be searched for."""
    chunks = split_document(_DOC)

    assert chunks[2].passage.startswith(
        "What the tie zone is — Why the whole range must clear it"
    )
    assert "Leaning past the band" in chunks[2].passage
