from app.echo_audit import EchoReport, compute_echo, format_echo_report

_BANK = frozenset({"fishing", "karaoke", "board games", "beekeeping"})


def test_compute_echo_on_a_worked_example() -> None:
    # US-0: 2 of 3 interests echo its own examples; all 3 are in the bank.
    # US-1: 0 of 2 echo (its examples were different); 1 of 2 is in the bank.
    # US-2: expected from the quotas but has no rows in the DB.
    interests_by_id = {
        "US-00000": ["Fishing", "karaoke", "board games"],
        "US-00001": ["beekeeping", "trail running"],
    }
    examples_by_id = {
        "US-00000": ["fishing", "karaoke", "pottery", "archery"],
        "US-00001": ["fishing", "karaoke", "board games", "cosplay"],
        "US-00002": ["fishing", "karaoke", "board games", "cosplay"],
    }
    bank_by_id = dict.fromkeys(examples_by_id, _BANK)

    report = compute_echo(interests_by_id, examples_by_id, bank_by_id)

    assert report.expected == 3
    assert report.found == 2
    assert report.interests_total == 5
    assert report.echo_rate == 2 / 5  # case-insensitive: "Fishing" echoes
    assert report.in_bank_rate == 4 / 5
    assert report.top[0] == ("fishing", 1)  # counted casefolded


def test_compute_echo_of_an_empty_pool_is_all_zero() -> None:
    report = compute_echo({}, {}, {})

    assert report == EchoReport(
        expected=0,
        found=0,
        interests_total=0,
        echo_rate=0.0,
        in_bank_rate=0.0,
        top=[],
    )


def test_format_echo_report_warns_on_expected_found_mismatch() -> None:
    # a silent mismatch would let a wrong --size/--seed measure the wrong pool
    short = EchoReport(
        expected=200, found=2, interests_total=5,
        echo_rate=0.4, in_bank_rate=0.8, top=[("fishing", 1)],
    )
    full = EchoReport(
        expected=2, found=2, interests_total=5,
        echo_rate=0.4, in_bank_rate=0.8, top=[("fishing", 1)],
    )

    assert "2 found of 200 expected" in format_echo_report(short)
    assert "WARNING" in format_echo_report(short)
    assert "WARNING" not in format_echo_report(full)
