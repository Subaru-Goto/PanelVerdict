"""The free parts of the Ragas runner (110/#238): what can be proven without a
model call. The paid run itself is `experiments/rag_eval.py`, by hand, and its
results are a research record — not a test."""

import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.corpus import _all_chunks
from experiments.rag_eval import (
    CASES_PATH,
    load_cases,
    reference_context,
    retrieved_passages,
    searched_for,
    select,
    why_unscored,
)


def test_every_case_names_a_passage_the_corpus_actually_has() -> None:
    """The reference context is a heading in the corpus, as written. A corpus
    edit that renames a section fails here, not as a silently wrong baseline."""
    headings = {(chunk.source, chunk.section) for chunk in _all_chunks()}
    cases = load_cases(CASES_PATH)

    assert len({case.id for case in cases}) == len(cases), "duplicate case id"
    for case in cases:
        assert (case.source, case.section) in headings, case.id


def test_the_set_covers_every_chunk_twice() -> None:
    """Decision Q2: two questions per chunk — one in the reader's jargon, one in
    their own words. Fifteen chunks, thirty cases; a chunk with none is a part
    of the corpus the baseline never looks at."""
    per_chunk: dict[tuple[str, str], int] = {}
    for case in load_cases(CASES_PATH):
        per_chunk[(case.source, case.section)] = (
            per_chunk.get((case.source, case.section), 0) + 1
        )

    assert set(per_chunk) == {(c.source, c.section) for c in _all_chunks()}
    assert all(n == 2 for n in per_chunk.values()), per_chunk


def test_the_reference_context_is_the_chunk_s_own_passage() -> None:
    case = load_cases(CASES_PATH)[0]
    passage = reference_context(case)

    assert passage.startswith(f"{case.source} — {case.section}")


def test_retrieved_passages_are_read_off_the_turn_s_tool_messages() -> None:
    """What the analyst actually retrieved is on the checkpointed transcript as
    the corpus tool's JSON result; a turn that never called it retrieved
    nothing, and says so as an empty list rather than an error."""
    found = [
        {
            "citation": "How the verdict is decided — The tie zone",
            "passage": "A band around even.",
        },
        {
            "citation": "How the verdict is decided — Why a range",
            "passage": "A range, not a number.",
        },
    ]
    messages = [
        HumanMessage(content="what is the tie zone"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "explain_the_report",
                    "args": {"question": "tie zone"},
                    "id": "c1",
                }
            ],
        ),
        ToolMessage(
            content=json.dumps(found), name="explain_the_report", tool_call_id="c1"
        ),
        # Another tool's result on the same turn: not a passage, not retrieval.
        # A reader of every ToolMessage either crashes on its shape or counts
        # the report's figures as corpus text.
        ToolMessage(
            content=json.dumps({"tally": {"a": 22, "b": 28}, "polling": "ran out"}),
            name="analyze_results",
            tool_call_id="c2",
        ),
        AIMessage(content="A band around even, so small differences count as ties."),
    ]

    assert retrieved_passages(messages) == [p["passage"] for p in found]
    assert (
        retrieved_passages([HumanMessage(content="hi"), AIMessage(content="hello")])
        == []
    )


def test_the_analyst_s_own_search_strings_are_read_off_the_turn() -> None:
    """The strings the analyst searched with, in order — it rewrites the
    reader's question, and a miss is diagnosed against what it sent (129/#313)."""
    messages = [
        HumanMessage(content="What has the panel actually been validated on?"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "explain_the_report",
                    "args": {"question": "what the panel is validated on"},
                    "id": "c1",
                },
                {"name": "analyze_results", "args": {}, "id": "c2"},
            ],
        ),
        ToolMessage(content="[]", name="explain_the_report", tool_call_id="c1"),
        ToolMessage(content="{}", name="analyze_results", tool_call_id="c2"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "explain_the_report",
                    "args": {"question": "panel limits headlines"},
                    "id": "c3",
                }
            ],
        ),
        ToolMessage(content="[]", name="explain_the_report", tool_call_id="c3"),
        AIMessage(content="Written headlines that say different things."),
    ]

    assert searched_for(messages) == [
        "what the panel is validated on",
        "panel limits headlines",
    ]
    assert searched_for([HumanMessage(content="hi"), AIMessage(content="hello")]) == []


def test_an_unscored_turn_says_whether_it_searched_at_all() -> None:
    """Searched-and-empty is a gate finding; never-searched is routing (129/#313)."""
    assert why_unscored(searched=[], retrieved=[]) == "never searched"
    assert (
        why_unscored(searched=["panel validated on"], retrieved=[])
        == "nothing passed the gate"
    )
    assert (
        why_unscored(searched=["tie zone"], retrieved=["A band around even."]) is None
    )


def test_a_limit_spreads_across_both_documents() -> None:
    """A dry run on `--limit 10` must price both documents, not the head of the
    file — the same reason 091's `select` spreads."""
    cases = load_cases(CASES_PATH)
    chosen = select(cases, 10)

    assert len(chosen) == 10
    assert {case.source for case in chosen} == {case.source for case in cases}
