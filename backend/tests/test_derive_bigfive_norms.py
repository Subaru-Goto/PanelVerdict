import json
from pathlib import Path

import pytest

from pipeline.derive_bigfive_norms import derive

_ARTIFACT = Path(__file__).parents[1] / "app" / "data" / "bigfive_norms.json"


def test_derive_reproduces_the_committed_artifact():
    # the committed norms must be exactly what the derivation produces from the
    # cited raw inputs — so a raw/derivation edit that isn't regenerated fails here
    assert derive() == json.loads(_ARTIFACT.read_text())


def test_derive_openness_16_19_female_from_raw():
    # independent hand-derivation from the raw T-scores + gender d:
    # z = ((50.45 + 51.75)/2 - 50)/10 = 0.110 ; pooled d_O = (-.15 + .12)/2 = -.015
    # μ(female) = z + d/2 = 0.110 - 0.0075 = 0.1025  (O is first in TRAIT_ORDER)
    assert derive()["mu"]["16-19|female"][0] == pytest.approx(0.1025)
