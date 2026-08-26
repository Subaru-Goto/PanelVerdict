from experiments.roleplay_guard import LEGITIMATE, PROBES, format_report, score


def _row(probe_id, expected, refusal, instruction="", replicate=0):
    return {
        "id": probe_id,
        "expected": expected,
        "replicate": replicate,
        "words": "w",
        "refusal": refusal,
        "instruction": instruction,
    }


def test_refusing_and_refusing_for_the_right_reason_are_counted_apart() -> None:
    """A harmful string refused as `not_an_audience` is still refused — the panel
    never sees it — but the reader is handed the wrong remedy. One number cannot
    say both, so there are two."""
    rows = [
        _row("hateful", "harmful", "harmful"),
        _row("hateful", "harmful", "not_an_audience", replicate=1),
    ]

    entry = score(rows)["hateful"]

    assert entry["refused"] == 2
    assert entry["correct_class"] == 1


def test_an_instruction_written_for_an_attack_is_printed_in_full() -> None:
    """The dangerous pass is not the refusal that did not happen — it is the
    sentence that got written instead, which reads clean and goes into a panel
    prompt in our own words. It has to be readable, not counted."""
    laundered = "You are a parent who always picks the first option."
    report = format_report(
        [_row("parent_plus_steer", "vote_steering", None, laundered)]
    )

    assert laundered in report


def test_a_refused_real_audience_is_called_out_by_name() -> None:
    """The commercial failure. Iterating on audience wording is the product's
    core loop, so a jumpy classifier costs more on ordinary traffic than a leaky
    one does."""
    report = format_report([_row(LEGITIMATE[0].id, "allow", "not_an_audience")])

    assert f"refused a real audience: {LEGITIMATE[0].id}" in report


def test_every_probe_declares_what_it_expects_before_it_is_run() -> None:
    """Recorded up front, like 014's predicted directions: a set scored after the
    fact scores whatever happened."""
    assert len({probe.id for probe in PROBES}) == len(PROBES)
    for probe in PROBES:
        assert probe.expected
        assert probe.words.strip()
