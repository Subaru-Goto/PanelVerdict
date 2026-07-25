import numpy as np
import pytest

from app.hobbies import HobbyBank, load_hobby_bank, sample_prompt_examples
from app.interests import _validate
from app.schemas import Locale

_BANK = HobbyBank(
    common=("fishing", "karaoke", "board games", "cycling", "cooking"),
    niche=("beekeeping", "lockpicking"),
)


@pytest.fixture
def hobby_dir(tmp_path, monkeypatch):
    rows = (
        "hobby,tier\n"
        "fishing,common\n"
        "karaoke,common\n"
        "board games,common\n"
        "beekeeping,niche\n"
    )
    (tmp_path / "us.csv").write_text(rows)
    monkeypatch.setattr("app.hobbies._HOBBY_DIR", tmp_path)
    return tmp_path


def test_load_hobby_bank_splits_rows_by_tier(hobby_dir) -> None:
    bank = load_hobby_bank(Locale.US)

    assert bank.common == ("fishing", "karaoke", "board games")
    assert bank.niche == ("beekeeping",)


def test_load_hobby_bank_rejects_an_unknown_tier(hobby_dir) -> None:
    (hobby_dir / "us.csv").write_text("hobby,tier\nfishing,sometimes\n")

    with pytest.raises(ValueError):
        load_hobby_bank(Locale.US)


def test_sample_prompt_examples_is_deterministic_per_seed() -> None:
    assert sample_prompt_examples(_BANK, np.random.default_rng(7)) == (
        sample_prompt_examples(_BANK, np.random.default_rng(7))
    )
    assert sample_prompt_examples(_BANK, np.random.default_rng(7)) != (
        sample_prompt_examples(_BANK, np.random.default_rng(8))
    )


def test_sample_prompt_examples_mixes_mostly_common_with_one_niche() -> None:
    examples = sample_prompt_examples(_BANK, np.random.default_rng(0))

    assert len(examples) == 4
    assert len(set(examples)) == 4
    assert sum(e in _BANK.common for e in examples) == 3
    assert sum(e in _BANK.niche for e in examples) == 1
    # plain str, not numpy str_ — the examples end up inside an f-string prompt
    assert all(type(e) is str for e in examples)


@pytest.mark.parametrize("country", list(Locale))
def test_committed_banks_pass_the_tag_gate(country: Locale) -> None:
    # a bank typo must fail here, not as a mysterious generation-time rejection
    bank = load_hobby_bank(country)
    entries = bank.common + bank.niche

    assert len(set(entries)) == len(entries)
    assert len(bank.common) >= 90  # enough spread to anchor a mainstream pool
    assert len(bank.niche) >= 40
    for entry in entries:
        _validate(["trail running", "home cooking", entry])
