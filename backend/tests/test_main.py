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

    # verdict counts both variants; constant option_1 vote + counterbalancing
    # means "a" wins (ties, if any, break to the first variant id).
    assert body["verdict"]["total"] == len(FIXED_PANEL)
    assert set(body["verdict"]["counts"]) == {"a", "b"}
    assert body["verdict"]["winner"] == "a"
