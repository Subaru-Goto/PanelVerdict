from fastapi.testclient import TestClient

from app.main import app, get_panel_llm
from app.panel import FIXED_PANEL
from tests.factories import voted


def test_evaluate_returns_verdict_variants_and_reasons(stub_llm) -> None:
    app.dependency_overrides[get_panel_llm] = lambda: stub_llm(
        chosen="option_1", reason="clear discount framing"
    )
    try:
        client = TestClient(app)
        response = client.post(
            "/evaluate",
            json={
                "headline_a": "Save 50% today",
                "headline_b": "Limited time: half price",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()

    # the two headlines are echoed back as identified variants
    assert body["variants"] == {
        "a": "Save 50% today",
        "b": "Limited time: half price",
    }

    # one vote per persona, reasons carried through for later quality review
    assert len(body["votes"]) == len(FIXED_PANEL)
    assert all(vote["reason"] == "clear discount framing" for vote in body["votes"])

    # the tally is descriptive; both variants are always reported
    assert body["tally"]["total"] == len(FIXED_PANEL)
    assert set(body["tally"]["counts"]) == {"a", "b"}
    assert "winner" not in body["tally"]

    # the verdict is the posterior plus a decision, and it carries its own band —
    # nothing in the payload names a winner.
    verdict = body["verdict"]
    assert verdict["rope"] == [0.43, 0.57]
    assert verdict["outcome"] in ("decisive", "practical_tie", "undecided")
    assert 0.0 <= verdict["share_preferring_b"] <= 1.0
    assert 0.0 <= verdict["probability_majority_prefers_b"] <= 1.0
    assert set(verdict["expected_preference_shortfall"]) == {"shipping_a", "shipping_b"}
    assert "winner" not in verdict


def test_evaluate_refuses_a_verdict_when_a_panelist_did_not_vote() -> None:
    """This panel is five personas, so one missing vote is a fifth of it — a verdict on
    four presented as a verdict on five is the half-panel 003 forbids. The response also
    must not carry the failure text out, which can include the model's own output."""

    class RefusingOne:
        def vote(self, *, system_prompt: str, option_1: str, option_2: str):
            if "61-year-old" in system_prompt:
                raise RuntimeError("api key sk-secret rejected")
            return voted()

    app.dependency_overrides[get_panel_llm] = RefusingOne
    try:
        response = TestClient(app).post(
            "/evaluate", json={"headline_a": "a", "headline_b": "b"}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail == f"1 of {len(FIXED_PANEL)} panelists did not vote (RuntimeError)"
    assert "sk-secret" not in detail
