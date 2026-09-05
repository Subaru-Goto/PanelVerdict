"""Which corpus passages pass the lexical gate for each RAG case — free, local.

`search_corpus` returns a passage only if more than half of the question's
stemmed content words appear in it (018/#124). This runs that test alone,
without the embedding, over the questions in `rag_cases.json` as the reader
wrote them, and reports each case whose target passage would never be
returned however the embedding ranked it. It found 7 of 30 on the first
baseline (129/#313); the defects are tracked in 130/#315.

The analyst rewrites the question before it searches, so this is a proxy for
the reader's wording, not a replay of a run. Pass case ids to narrow it.

    PYTHONPATH=. uv run python experiments/gate_probe.py
    PYTHONPATH=. uv run python experiments/gate_probe.py p-limit-1 v-measure-2
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import psycopg

from app.config import settings

CASES = Path(__file__).with_name("rag_cases.json")

# The question's distinct lexemes, exactly as `_SEARCH`'s `asked` CTE derives them.
_LEXEMES = """
SELECT array_agg(DISTINCT lexeme)
FROM unnest(tsvector_to_array(to_tsvector('english', %s))) AS lexeme
"""

# Per passage: how many of the question's lexemes it contains, and the keyword
# rank the sparse half would give it.
_HITS = """
SELECT
    section,
    (SELECT count(*) FROM unnest(%(lexemes)s::text[]) AS l
     WHERE search @@ quote_literal(l)::tsquery) AS hits,
    ts_rank(search, (SELECT string_agg(quote_literal(l), ' | ')
                     FROM unnest(%(lexemes)s::text[]) AS l)::tsquery) AS rank
FROM corpus_chunks
ORDER BY rank DESC
"""


def main() -> None:
    wanted = set(sys.argv[1:])
    cases = json.loads(CASES.read_text())["cases"]
    failing = 0
    with psycopg.connect(settings.database_url) as conn:
        for case in cases:
            if wanted and case["id"] not in wanted:
                continue
            row = conn.execute(_LEXEMES, (case["question"],)).fetchone()
            assert row is not None
            (lexemes,) = row
            rows = conn.execute(_HITS, {"lexemes": lexemes}).fetchall()
            passing = [(s, h) for s, h, _ in rows if h * 2 > len(lexemes)]
            target_hits = next(h for s, h, _ in rows if s == case["section"])
            ok = target_hits * 2 > len(lexemes)
            failing += not ok
            print(
                f"{case['id']}: {'pass' if ok else 'FAIL'}"
                f"  lexemes={lexemes}  target hits={target_hits}"
                f"  passing={[s for s, _ in passing]}"
            )
    print(
        f"\n{failing} of {len(cases) if not wanted else len(wanted)} targets fail the gate"
    )


if __name__ == "__main__":
    main()
