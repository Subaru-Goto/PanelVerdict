import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import (
    app,
    budget_notice,
    get_conn,
    get_panel_llm,
    get_remaining_credit,
    get_translator,
)
from app.persistence import persist_pool
from app.vote import OutOfCredit
from tests.factories import (
    StubTranslator,
    make_assembled,
    make_persona,
    seed_japanese,
    voted,
)

# What the endpoint should pass through as `requested`. Read from settings rather
# than written as a number, because the test environment pins the profile — the
# assertion is that the endpoint forwards the configured size, not what the size is.
_SIZE = settings.panel.size

_REQUEST_BODY = {
    "target_description": "Japanese homeowners",
    "headline_a": "Save 50% today",
    "headline_b": "Limited time: half price",
}


@pytest.fixture
def client(conn, stub_llm):
    """The app with every paid or external dependency replaced: the testcontainer
    connection, a canned translator, and a stub panel model."""
    # Every override is a zero-argument callable, never the class itself: FastAPI
    # reads an override's signature as a dependency, so `StubTranslator` bare would
    # turn its `request: TargetRequest` parameter into the endpoint's body model.
    app.dependency_overrides[get_conn] = lambda: conn
    app.dependency_overrides[get_translator] = lambda: StubTranslator()
    app.dependency_overrides[get_panel_llm] = lambda: stub_llm(
        chosen="option_1", reason="clear discount framing"
    )
    # No network in tests: the credit check is a live GET when not overridden.
    app.dependency_overrides[get_remaining_credit] = lambda: None
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_evaluate_returns_the_full_panel_test_payload(client, conn) -> None:
    seed_japanese(conn, 5)

    response = client.post("/evaluate", json=_REQUEST_BODY)

    assert response.status_code == 200
    body = response.json()

    # the two headlines are echoed back as identified variants
    assert body["variants"] == {
        "a": "Save 50% today",
        "b": "Limited time: half price",
    }

    # one vote per matched persona, reasons carried through for later quality review
    assert len(body["votes"]) == 5
    assert all(vote["reason"] == "clear discount framing" for vote in body["votes"])

    # each vote carries its voter as a person — demographics plus the five trait
    # levels — while the ledger's provenance (test_id, presentation_order) stays
    # off the wire (023)
    vote = body["votes"][0]
    assert set(vote) == {"persona_id", "chosen_variant_id", "reason", "voter"}
    assert vote["voter"]["country"] == "JP"
    assert set(vote["voter"]) == {
        "country",
        "age",
        "gender",
        "education",
        "income_band",
        "traits",
    }
    assert set(vote["voter"]["traits"]) == {
        "openness",
        "conscientiousness",
        "extraversion",
        "agreeableness",
        "neuroticism",
    }

    # what the verdict is a verdict *on*: the three counts, the query the panel was
    # drawn under (coverage as data, not just the country list), and the notices
    assert body["counts"] == {"requested": _SIZE, "matched": 5, "voted": 5}
    assert body["query"]["countries"] == ["JP"]
    assert body["query"]["coverage"] == "requested"
    assert isinstance(body["notices"], list)

    # a single-chunk run at the dev size ends by exhaustion, not by decision
    assert body["stop_reason"] is None

    # the tally is descriptive; both variants are always reported
    assert body["tally"]["total"] == 5
    assert set(body["tally"]["counts"]) == {"a", "b"}
    assert "winner" not in body["tally"]

    # the verdict is the posterior plus the band's probabilities, and it carries its
    # own band — nothing in the payload names a winner.
    verdict = body["verdict"]
    assert verdict["rope"] == [0.43, 0.57]
    assert 0.0 <= verdict["share_preferring_b"] <= 1.0
    assert 0.0 <= verdict["probability_majority_prefers_b"] <= 1.0
    assert set(verdict["probability_meaningfully_preferred"]) == {"a", "b"}
    assert 0.0 <= verdict["probability_practical_tie"] <= 1.0
    assert set(verdict["expected_preference_shortfall"]) == {"shipping_a", "shipping_b"}
    assert "winner" not in verdict


def test_a_shortfall_notice_reaches_the_response(client, conn) -> None:
    seed_japanese(conn, 2)

    body = client.post("/evaluate", json=_REQUEST_BODY).json()

    assert body["counts"] == {"requested": _SIZE, "matched": 2, "voted": 2}
    assert any(
        f"Only 2 of the {_SIZE}" in notice["message"] for notice in body["notices"]
    )


def test_a_target_nobody_matches_is_the_requests_fault(client, conn) -> None:
    """422, not 502: the pool is fine and the provider was never called — the target
    named an audience this pool cannot serve."""
    persist_pool(conn, [make_assembled(make_persona(id_="US-00000", country="US"))])

    response = client.post("/evaluate", json=_REQUEST_BODY)

    assert response.status_code == 422
    assert "no persona matches" in response.json()["detail"]


def test_a_panel_with_no_votes_is_a_bad_gateway_naming_types_only(client, conn) -> None:
    seed_japanese(conn, 3)

    class Failing:
        configuration = "stub"

        def vote(self, *, system_prompt: str, option_1: str, option_2: str):
            raise RuntimeError("api key sk-secret rejected")

    app.dependency_overrides[get_panel_llm] = Failing

    response = client.post("/evaluate", json=_REQUEST_BODY)

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail == "0 of 3 panelists voted (RuntimeError)"
    assert "sk-secret" not in detail


def test_a_partial_run_returns_a_verdict_with_the_shortfall_in_the_counts(
    client, conn
) -> None:
    """The 5-persona all-or-nothing refusal is retired, and by 010b's decision no
    threshold replaces it: every run with at least one vote gets a verdict, and the
    customer is informed through the counts and a notice rather than refused."""
    seed_japanese(conn, 3)

    class RefusingOne:
        configuration = "stub"

        def vote(self, *, system_prompt: str, option_1: str, option_2: str):
            if "31-year-old" in system_prompt:
                raise RuntimeError("transient")
            return voted()

    app.dependency_overrides[get_panel_llm] = RefusingOne

    response = client.post("/evaluate", json=_REQUEST_BODY)

    assert response.status_code == 200
    body = response.json()
    assert body["counts"] == {"requested": _SIZE, "matched": 3, "voted": 2}
    assert body["tally"]["total"] == 2
    assert any(
        "1 of the 3" in notice["message"] and "did not vote" in notice["message"]
        for notice in body["notices"]
    )


def test_exhausted_credit_is_a_402_naming_the_remedy(client, conn) -> None:
    """Not a 502: the server did nothing wrong, and 'bad gateway' sends a human to
    the wrong place. The 402 carries what to do — and no provider text."""
    seed_japanese(conn, 3)

    class Broke:
        configuration = "stub"

        def vote(self, *, system_prompt: str, option_1: str, option_2: str):
            raise OutOfCredit("OpenRouter credit exhausted (402)")

    app.dependency_overrides[get_panel_llm] = lambda: Broke()

    response = client.post("/evaluate", json=_REQUEST_BODY)

    assert response.status_code == 402
    detail = response.json()["detail"]
    assert "Top up and re-run" in detail
    assert "not charged" in detail


class TestBudgetNotice:
    """010f's pre-flight, decided as warn-and-proceed: a run the credit cannot
    finish is still worth starting, because every vote it casts is saved and a
    re-run after top-up resumes free. So the check informs; it never refuses."""

    def test_thin_credit_warns_with_both_figures(self) -> None:
        (notice,) = budget_notice(0.05, size=200)

        assert notice.severity == "warning"
        assert "$0.05" in notice.message
        assert "$0.15" in notice.message
        assert "top" in notice.message and "re-run" in notice.message

    def test_sufficient_credit_says_nothing(self) -> None:
        assert budget_notice(5.00, size=200) == ()

    def test_an_unknown_balance_never_warns(self) -> None:
        """None is an unlimited key or a failed check — a broken meter must not
        cry wolf over a run it cannot price."""
        assert budget_notice(None, size=200) == ()


def test_the_preflight_warning_reaches_the_response(client, conn) -> None:
    seed_japanese(conn, 3)
    app.dependency_overrides[get_remaining_credit] = lambda: 0.01

    response = client.post("/evaluate", json=_REQUEST_BODY)

    assert response.status_code == 200
    messages = [n["message"] for n in response.json()["notices"]]
    assert any("credit" in m and "re-run" in m for m in messages)
