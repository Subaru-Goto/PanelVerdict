"""Split a corpus document into retrievable chunks.

The corpus explains what the report *means* — what a trait level says, what the
tie zone is, why "ahead" is not "decisive". It holds concepts, never figures:
every number a reader needs is already on the wire, and a second copy in a
document is a copy that can disagree with the report beside it.

Splitting follows the headings rather than a fixed window, because a heading is
where the author put a claim together with the caveat that qualifies it.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import psycopg


@dataclass(frozen=True)
class Chunk:
    """One retrievable passage, carrying the citation shown to the reader.

    `source` is the document's title and `section` its heading, both as written
    — a citation a reader can check has to be words, not a file path.
    """

    source: str
    section: str
    text: str

    @property
    def passage(self) -> str:
        """What is embedded and keyword-indexed: the heading, then the body.

        A heading is written in the reader's words and the body under it often
        never repeats them, so matching the body alone misses the one line
        chosen to be searched for.
        """
        return f"{self.source} — {self.section}\n\n{self.text}"


def split_document(markdown: str) -> list[Chunk]:
    """Chunk one document at its headings, title first.

    The opening paragraph is a chunk of its own, filed under the title: it is
    where a document says the thing it is about.
    """
    title = ""
    section = ""
    lines: list[str] = []
    chunks: list[Chunk] = []

    def close() -> None:
        text = "\n".join(lines).strip()
        if text:
            chunks.append(Chunk(source=title, section=section, text=text))
        lines.clear()

    for line in markdown.splitlines():
        if line.startswith("# "):
            close()
            title = section = line[2:].strip()
        elif line.startswith("## "):
            close()
            section = line[3:].strip()
        else:
            lines.append(line)
    close()
    return chunks


# The corpus is small, first-party and definitional, so it is read from disk once
# at import rather than cached behind anything: two documents, a handful of
# sections each.
_CORPUS_DIR = Path(__file__).parent / "data" / "corpus"


def load_corpus() -> dict[str, str]:
    """Every committed corpus document, by filename.

    Read from `app/data/corpus/` rather than `docs/`, because these ship with the
    backend: the seed needs them wherever it runs, and they are product content
    rather than notes about the project.
    """
    return {path.name: path.read_text() for path in sorted(_CORPUS_DIR.glob("*.md"))}


def _all_chunks() -> list[Chunk]:
    return [chunk for text in load_corpus().values() for chunk in split_document(text)]


DOCUMENTS: list[Chunk] = _all_chunks()


@dataclass(frozen=True)
class Passage:
    """A retrieved chunk with the citation the reader is shown.

    Separate from `Chunk` because a citation is not optional here: this is what
    crosses into the analyst's context, and a passage that arrived without its
    source could be quoted as if it were the model's own knowledge.
    """

    source: str
    section: str
    passage: str

    @property
    def citation(self) -> str:
        return f"{self.source} — {self.section}"


class Embedder(Protocol):
    """The seam the corpus depends on, so a test never needs a paid call."""

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def seed_corpus(conn: psycopg.Connection, embedder: Embedder) -> int:
    """Replace the corpus with what is committed on disk. Returns the row count.

    Drop-and-reseed rather than a migration, for 006j's reason: the corpus is a
    cache of documents that live in git, so the table can always be rebuilt and
    nothing in it is worth migrating. Deleted in the same transaction as the
    insert, so a failed embed leaves the old corpus serving rather than an empty
    table.
    """
    chunks = DOCUMENTS
    vectors = embedder.embed([chunk.passage for chunk in chunks])
    with conn.transaction():
        conn.execute("DELETE FROM corpus_chunks")
        conn.cursor().executemany(
            "INSERT INTO corpus_chunks (id, source, section, passage, embedding)"
            " VALUES (%s, %s, %s, %s, %s)",
            [
                (
                    f"{chunk.source}#{i}",
                    chunk.source,
                    chunk.section,
                    chunk.passage,
                    str(vector),
                )
                for i, (chunk, vector) in enumerate(zip(chunks, vectors))
            ],
        )
    return len(chunks)


# Reciprocal-rank fusion. The constant damps the top of each list so one search
# cannot win on its own: a passage ranked first by keyword and nowhere by vector
# scores below one ranked second by both. 60 is the value the method was published
# with (Cormack, Clarke & Buettcher 2009, "Reciprocal Rank Fusion outperforms
# Condorcet and individual Rank Learning Methods"), used unchanged — this corpus
# is far too small for tuning it to mean anything.
_RRF_K = 60

_SEARCH = """
WITH dense AS (
    SELECT id, row_number() OVER (ORDER BY embedding <=> %(vector)s) AS rank
    FROM corpus_chunks
    ORDER BY embedding <=> %(vector)s
    LIMIT %(pool)s
),
sparse AS (
    SELECT id, row_number() OVER (
        ORDER BY ts_rank(search, websearch_to_tsquery('english', %(query)s)) DESC
    ) AS rank
    FROM corpus_chunks
    WHERE search @@ websearch_to_tsquery('english', %(query)s)
    LIMIT %(pool)s
)
SELECT c.source, c.section, c.passage
FROM corpus_chunks c
JOIN sparse ON sparse.id = c.id
JOIN (
    SELECT id, sum(score) AS fused FROM (
        SELECT id, 1.0 / (%(k)s + rank) AS score FROM dense
        UNION ALL
        SELECT id, 1.0 / (%(k)s + rank) AS score FROM sparse
    ) scored
    GROUP BY id
) f ON f.id = c.id
ORDER BY f.fused DESC
LIMIT %(limit)s
"""


def search_corpus(
    conn: psycopg.Connection,
    query: str,
    embedder: Embedder,
    *,
    limit: int = 4,
) -> list[Passage]:
    """Retrieve passages explaining the report, most relevant first.

    Hybrid because the reader's questions arrive in two registers. Some are exact
    jargon read off the screen — "practical tie", "credible interval" — where a
    keyword index beats an embedding outright. Others are the same question in
    their own words — "why isn't this a result?" — where only the embedding will
    do. Fused by reciprocal rank rather than by blending scores, because the two
    produce numbers on incomparable scales and only their orderings mean anything.

    Both halves in one statement: at this corpus size the whole thing is a
    sequential scan either way, and two round trips would buy nothing.

    **A passage must be lexically matched to be returned at all**; the embedding
    decides the order, not the membership. This is the one place the two halves
    are not equals, and it is deliberate: a vector search always returns its
    nearest neighbours however far away they are, so a question the corpus cannot
    answer would come back with a confident passage and a citation attached — the
    exact failure this corpus exists to prevent, made worse by looking sourced.
    Nothing lexically matched means no passage, and the analyst says so.

    What that costs is recall on a question sharing no word with any passage. It
    is a small cost *here* — this corpus explains the words printed on the report,
    so a reader asking about them tends to use them — and it is the safe direction
    to be wrong in. The alternative is a distance floor on the dense half, which
    needs a measured threshold rather than a guessed one; owed on 018 if the
    judged run shows paraphrases being missed.
    """
    if not query.strip():
        return []
    (vector,) = embedder.embed([query])
    rows = conn.execute(
        _SEARCH,
        {
            "vector": str(vector),
            "query": query,
            "k": _RRF_K,
            # Deeper than `limit` so fusion has ranks to work with: a passage the
            # keyword half puts fourth may still win once both halves agree.
            "pool": max(limit * 3, 10),
            "limit": limit,
        },
    ).fetchall()
    return [Passage(source=s, section=sec, passage=p) for s, sec, p in rows]
