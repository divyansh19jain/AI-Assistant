from app.ai.caseworker_review import documents_likely_needed


def test_documents_for_employed_noncitizen_with_bills_and_ssn():
    answers = {
        "income.has_employment": "employed",
        "person1.us_citizen_or_national": False,
        "person1.medical_bills_last_3_months": True,
        "person1.ssn": "123456789",
    }
    docs = {d["document"] for d in documents_likely_needed(answers)}
    assert "Photo ID" in docs
    assert "Recent pay stubs" in docs
    assert "Immigration documents" in docs
    assert "Recent medical bills (last 3 months)" in docs
    assert "Social Security card" in docs


def test_documents_minimal_is_just_id():
    assert {d["document"] for d in documents_likely_needed({})} == {"Photo ID"}


def test_self_employed_suggests_records_not_paystubs():
    docs = {d["document"] for d in documents_likely_needed({"income.has_employment": "self_employed"})}
    assert "Self-employment records" in docs
    assert "Recent pay stubs" not in docs


def test_caseworker_review_endpoint_returns_view(client):
    sid = client.post(
        "/api/session/create", json={"form_id": "ODM_07216", "manual_mode": True}
    ).json()["session_id"]
    r = client.get(f"/api/session/{sid}/caseworker-review")
    assert r.status_code == 200, r.text
    data = r.json()
    assert set(["ready", "summary", "remaining", "needs_confirmation", "documents_likely_needed"]).issubset(data)
    assert any(d["document"] == "Photo ID" for d in data["documents_likely_needed"])
    # A brand-new session has required fields still remaining.
    assert data["summary"]["remaining"] > 0
