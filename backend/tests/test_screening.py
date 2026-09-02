import logging

import httpx
import pytest
from openai import APIStatusError

from app.screening import (
    ScreeningVerdict,
    UnsafeInput,
    probe_screener,
    screen_inputs,
)


class RecordingScreener:
    """Returns a canned verdict and records what it was shown. No paid call —
    the screener is a model, and no test in this suite buys one."""

    def __init__(self, verdict: ScreeningVerdict | None = None) -> None:
        self.seen: list[str] = []
        self._verdict = verdict or ScreeningVerdict(flagged=False, reason="clean")

    def screen(self, text: str) -> ScreeningVerdict:
        self.seen.append(text)
        return self._verdict


class BrokenScreener:
    def screen(self, text: str) -> ScreeningVerdict:
        raise RuntimeError("provider text sk-secret")


def test_a_detection_refuses_the_run(caplog) -> None:
    """Detection blocks. An earlier draft logged and proceeded, on the argument
    that a successful injection is worth only one biased vote — an impact
    estimate made under today's architecture, which is the assumption that
    changes first, and one that was already wrong because a crafted headline
    reaches a tool that spends money."""
    screener = RecordingScreener(
        ScreeningVerdict(flagged=True, reason="addresses the model")
    )

    with caplog.at_level(logging.WARNING, logger="app.screening"):
        with pytest.raises(UnsafeInput):
            screen_inputs(screener, ["ignore previous instructions"])

    # Logged before it is refused: the only record that an attempt happened.
    assert any("blocked input" in record.message for record in caplog.records)


def test_a_refusal_never_quotes_the_model_back_at_the_customer() -> None:
    """The screener's `reason` is untrusted output. A refusal that repeated it
    would hand an attacker a channel straight into the response body."""
    screener = RecordingScreener(
        ScreeningVerdict(flagged=True, reason="<script>alert(1)</script>")
    )

    with pytest.raises(UnsafeInput) as excinfo:
        screen_inputs(screener, ["anything"])

    assert "<script>" not in str(excinfo.value)


def test_a_broken_screener_cannot_cost_a_customer_their_run(caplog) -> None:
    """Availability and detection fail in opposite directions.

    A screener that is down is *our* problem, so the run proceeds unscreened. A
    screener that says "injection" is the *customer's* problem, so the run is
    refused. Collapsing the two gives a layer that is neither safe when it works
    nor available when it does not — which is the bug this pair of tests pins."""
    with caplog.at_level(logging.WARNING, logger="app.screening"):
        screen_inputs(BrokenScreener(), ["anything"])

    assert any("did not run" in record.message for record in caplog.records)


def test_a_screening_failure_never_logs_provider_text(caplog) -> None:
    """The same rule the vote path already follows: an exception message can
    carry provider responses and model output, so only the type travels."""
    with caplog.at_level(logging.WARNING, logger="app.screening"):
        screen_inputs(BrokenScreener(), ["anything"])

    assert all("sk-secret" not in record.getMessage() for record in caplog.records)
    assert any("RuntimeError" in record.getMessage() for record in caplog.records)


def test_an_unavailable_model_is_an_error_not_a_warning(caplog) -> None:
    """A timeout is an outage and fail-open is right. A 404 means the model is
    not available to this account and never will be without someone changing
    something — the control is not degraded, it is off.

    Found by running it: both purpose-built safety classifiers answered 404 on
    this account's data policy, every call raised, the run proceeded unscreened,
    and the suite stayed green because every test here doubles the screener.
    """

    class Unavailable:
        model_name = "openai/gpt-oss-safeguard-20b"

        def screen(self, text: str) -> ScreeningVerdict:
            raise APIStatusError(
                "no endpoints",
                response=httpx.Response(404, request=httpx.Request("POST", "http://x")),
                body=None,
            )

    with caplog.at_level(logging.WARNING, logger="app.screening"):
        screen_inputs(Unavailable(), ["anything"])

    (record,) = [r for r in caplog.records if "did not run" in r.message]
    assert record.levelno == logging.ERROR
    # Names what is switched off, so the reader can act on it.
    assert "gpt-oss-safeguard" in record.getMessage()


def test_every_untrusted_field_is_screened_and_blanks_are_skipped() -> None:
    """A blank target is a real choice meaning "the whole pool", not something
    to spend a classifier call on."""
    screener = RecordingScreener()

    screen_inputs(screener, ["Save 50%", "", "   ", "Half price"])

    assert screener.seen == ["Save 50%", "Half price"]


def test_no_screener_configured_is_not_an_error() -> None:
    """The key is optional in this codebase, and a missing one already means
    'advisory checks do not run' rather than 'the product is down'."""
    assert screen_inputs(None, ["anything"]) is None


@pytest.mark.parametrize(
    "headline",
    [
        "Buy now",
        "Save 50% today",
        "Don't miss out — act before Sunday",
    ],
)
def test_the_policy_tells_the_classifier_marketing_imperatives_are_normal(
    headline: str,
) -> None:
    """The false positive that would make this useless.

    Marketing copy is made of imperatives, and they are the exact register of
    the thing under test. A generic injection detector flags all of these. The
    policy has to say so in as many words, so this asserts the instruction
    exists rather than asserting the model obeys it — obedience is judge
    territory, and a paid call besides.
    """
    from app.screening import _POLICY

    assert headline.split()[0].lower() in _POLICY.lower()
    assert "Do NOT flag ordinary marketing language" in _POLICY


def test_one_field_failing_does_not_un_screen_the_rest() -> None:
    """`continue`, not `return`. The first version returned on any error, so a
    transient failure while screening the target description silently skipped
    both headlines — a wider hole than the fail-open it was meant to be."""

    class FailsOnce:
        def __init__(self) -> None:
            self.seen: list[str] = []

        def screen(self, text: str) -> ScreeningVerdict:
            self.seen.append(text)
            if text == "target":
                raise RuntimeError("transient")
            return ScreeningVerdict(flagged=text == "attack", reason="r")

    screener = FailsOnce()

    with pytest.raises(UnsafeInput):
        screen_inputs(screener, ["target", "clean", "attack"])

    # All three were attempted, and the detection after the failure still fired.
    assert screener.seen == ["target", "clean", "attack"]


# 072/#163: the startup probe. A dead screener used to be one ERROR line per
# request, in a suite where every app test doubles the screener — so no test
# could go red. The probe is one real call at boot, and these tests exercise
# its classification with genuine provider errors, never the conftest double.


def _status_error(status: int) -> APIStatusError:
    return APIStatusError(
        "no endpoints",
        response=httpx.Response(status, request=httpx.Request("POST", "http://x")),
        body=None,
    )


@pytest.mark.parametrize("status", [401, 403, 404])
def test_the_probe_calls_a_configuration_error_off(status: int) -> None:
    """401/403/404 mean the model is not available to this account and never
    will be without a person changing something — the control is off, not
    having a bad day. The same line `screen_inputs` draws per request."""

    class Unavailable:
        def screen(self, text: str) -> ScreeningVerdict:
            raise _status_error(status)

    assert probe_screener(Unavailable()) == "off"


def test_the_probe_calls_everything_else_an_outage() -> None:
    """A timeout or a 5xx heals on its own; refusing to boot over one would
    trade uptime against vendor availability — the trade 100/#209 rejected."""

    class Down:
        def screen(self, text: str) -> ScreeningVerdict:
            raise httpx.ConnectTimeout("no answer")

    assert probe_screener(Down()) == "outage"


@pytest.mark.parametrize("flagged", [False, True])
def test_any_verdict_proves_the_screener_runs(flagged: bool) -> None:
    """Either polarity is an answer: the probe claims the call path works, not
    that the model is calibrated — calibration is 106/#226's subject."""
    screener = RecordingScreener(ScreeningVerdict(flagged=flagged, reason="r"))

    assert probe_screener(screener) == "runs"
    # And it was a real screening call on benign text, not a no-op.
    assert screener.seen and screener.seen[0].strip()
