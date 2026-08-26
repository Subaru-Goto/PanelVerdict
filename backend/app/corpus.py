"""Split a corpus document into retrievable chunks.

The corpus explains what the report *means* — what a trait level says, what the
tie zone is, why "ahead" is not "decisive". It holds concepts, never figures:
every number a reader needs is already on the wire, and a second copy in a
document is a copy that can disagree with the report beside it.

Splitting follows the headings rather than a fixed window, because a heading is
where the author put a claim together with the caveat that qualifies it.
"""

from dataclasses import dataclass


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
