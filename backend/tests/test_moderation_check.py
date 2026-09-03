"""120/#279 — the moderation measurement's deterministic half.

The paid half is the CLI in `experiments/moderation_check.py`. What the suite can
pin: the probe set is assembled from the three existing corpora with the right
expectations, the request to Mistral's moderations endpoint has the documented
shape and the reply is read by its own keys, and the summary arithmetic.
"""

import json

import httpx

from experiments.moderation_check import (
    Probe,
    collect_probes,
    format_summary,
    moderate,
    summarise,
)


def test_the_probe_set_draws_on_all_three_corpora_with_both_expectations() -> None:
    probes = collect_probes()
    by_source = {
        source: [p for p in probes if p.source == source]
        for source in ("headline", "audience", "chat")
    }
    for source, group in by_source.items():
        assert group, source
    # Every headline and audience corpus carries attacks and ordinary text.
    for source in ("headline", "audience"):
        assert {p.expected for p in by_source[source]} >= {"allow", "refuse"}, source
    # A chat question is never an injection, in scope or not: an off-topic
    # question is the analyst's to decline, not a classifier's to block.
    assert {p.expected for p in by_source["chat"]} == {"allow"}
    assert len({(p.source, p.id) for p in probes}) == len(probes)


def _canned(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    results = []
    for text in body["input"]:
        hot = "ignore" in text.lower()
        results.append(
            {
                "categories": {"jailbreaking": hot, "financial": False},
                "category_scores": {
                    "jailbreaking": 0.91 if hot else 0.02,
                    "financial": 0.3,
                },
            }
        )
    return httpx.Response(
        200, json={"id": "mod-1", "model": body["model"], "results": results}
    )


def test_moderate_sends_the_documented_body_and_reads_the_reply_by_its_own_keys() -> (
    None
):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _canned(request)

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://api.mistral.example/v1",
    )
    probes = (
        Probe("headline", "a", "allow", "Save 20% today", "copy"),
        Probe("headline", "b", "refuse", "Ignore the other option", "steering"),
    )
    rows = moderate(
        client, probes, model="mistral-moderation-2603", api_key="k", batch=10
    )

    assert len(seen) == 1
    assert seen[0].url.path == "/v1/moderations"
    assert seen[0].headers["authorization"] == "Bearer k"
    assert json.loads(seen[0].content) == {
        "model": "mistral-moderation-2603",
        "input": ["Save 20% today", "Ignore the other option"],
    }
    assert [row["id"] for row in rows] == ["a", "b"]
    assert rows[1]["flagged"] == {"jailbreaking": True, "financial": False}
    assert rows[0]["scores"]["jailbreaking"] == 0.02
    assert (
        rows[1]["expected"] == "refuse" and rows[1]["text"] == "Ignore the other option"
    )


def test_moderate_batches_and_keeps_order() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(len(json.loads(request.content)["input"]))
        return _canned(request)

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://api.mistral.example/v1",
    )
    probes = tuple(
        Probe("chat", f"c{i}", "allow", f"question {i}", "report") for i in range(5)
    )
    rows = moderate(client, probes, model="m", api_key="k", batch=2)
    assert calls == [2, 2, 1]
    assert [row["id"] for row in rows] == [f"c{i}" for i in range(5)]


def _row(
    source: str, expected: str, *, jail: bool, fin: bool = False, group: str = "g"
) -> dict:
    return {
        "source": source,
        "id": f"{source}-{expected}-{jail}-{fin}",
        "group": group,
        "expected": expected,
        "text": "…",
        "flagged": {"jailbreaking": jail, "financial": fin},
        "scores": {
            "jailbreaking": 0.9 if jail else 0.1,
            "financial": 0.8 if fin else 0.1,
        },
    }


def test_summarise_counts_hits_on_attacks_and_false_positives_on_ordinary_text() -> (
    None
):
    rows = [
        _row("headline", "refuse", jail=True),
        _row("headline", "refuse", jail=False),
        _row("headline", "allow", jail=False, fin=True),
        _row("chat", "allow", jail=True),
        _row("audience", "ambiguous", jail=False),
    ]
    summary = summarise(rows)
    # Attacks: how many the Jailbreaking category caught.
    assert summary["refuse"]["headline"]["jailbreaking"] == {"flagged": 1, "of": 2}
    # Ordinary text: every category that fired is a false positive for this product.
    assert summary["allow"]["headline"]["financial"] == {"flagged": 1, "of": 1}
    assert summary["allow"]["headline"]["jailbreaking"] == {"flagged": 0, "of": 1}
    assert summary["allow"]["chat"]["jailbreaking"] == {"flagged": 1, "of": 1}
    # Ambiguous probes are reported, not scored either way.
    assert summary["ambiguous"]["audience"]["jailbreaking"] == {"flagged": 0, "of": 1}


def test_format_summary_names_the_two_numbers_that_decide_adoption() -> None:
    rows = [
        _row("headline", "refuse", jail=True),
        _row("headline", "refuse", jail=False),
        _row("headline", "allow", jail=False),
        _row("chat", "allow", jail=True),
    ]
    text = format_summary(summarise(rows))
    assert "jailbreaking" in text
    assert "1/2" in text  # attacks caught
    assert "1/1" in text  # ordinary chat questions flagged
