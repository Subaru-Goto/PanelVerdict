from fastapi.testclient import TestClient

from app.main import app, get_panel_llm
from app.panel import FIXED_PANEL


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
