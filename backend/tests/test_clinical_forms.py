def _clinical_gates(*selected: str) -> dict[str, bool]:
    keys = [
        "dsm5_level1", "phq9", "gad7", "cssrs", "auditc", "taps",
        "dast10", "pcl5", "mdq", "whodas12", "dla20",
    ]
    chosen = set(selected)
    return {f"selected.{key}": key in chosen for key in keys}


def test_clinical_scoring_phq9_total_and_interpretation():
    from app.clinical.scoring import score_clinical_battery

    answers = {"selected.phq9": True}
    answers.update({f"phq9.q{i}": "Nearly every day" for i in range(1, 10)})

    scores = score_clinical_battery("BH_SELF_REPORT_BATTERY", answers)

    phq9 = next(score for score in scores if score["tool_key"] == "phq9")
    assert phq9["total_score"] == 27
    assert phq9["max_score"] == 27
    assert "Severe" in phq9["interpretation"]


def test_clinical_scoring_whodas_uses_zero_to_four_simple_score():
    from app.clinical.scoring import score_clinical_battery

    answers = {"selected.whodas12": True}
    answers.update({f"whodas12.q{i}": "Extreme or cannot do" for i in range(1, 13)})

    whodas = next(
        score for score in score_clinical_battery("BH_SELF_REPORT_BATTERY", answers)
        if score["tool_key"] == "whodas12"
    )
    assert whodas["total_score"] == 48
    assert whodas["max_score"] == 48
    assert whodas["transformed_score"] == 100


def test_clinical_session_initial_answers_gate_selected_tools(client):
    session = client.post(
        "/api/session/create",
        json={
            "form_id": "BH_SELF_REPORT_BATTERY",
            "manual_mode": True,
            "initial_answers": _clinical_gates("phq9"),
        },
    ).json()

    assert session["form_id"] == "BH_SELF_REPORT_BATTERY"
    assert session["next_question"]["field_key"] == "client.first_name"

    review = client.get(f"/api/session/{session['session_id']}/review").json()
    assert "phq9.q1" in review["missing_applicable"]
    assert "gad7.q1" not in review["missing_applicable"]
    assert "selected.phq9" not in review["missing_applicable"]


def test_clinical_results_api_exposes_client_assessment_data_and_scores(client, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("CLINICAL_RESULTS_API_KEYS", "test-clinical-key")
    get_settings.cache_clear()
    try:
        session = client.post(
            "/api/session/create",
            json={
                "form_id": "BH_SELF_REPORT_BATTERY",
                "manual_mode": True,
                "initial_answers": _clinical_gates("phq9"),
            },
        ).json()
        session_id = session["session_id"]
        for field_key, raw in {
            "client.first_name": "Amy",
            "client.last_name": "Jones",
            "client.dob": "1980-01-05",
            **{f"phq9.q{i}": "Not at all" for i in range(1, 9)},
            "phq9.q9": "Several days",
        }.items():
            result = client.post(
                f"/api/session/{session_id}/answer",
                json={"field_key": field_key, "raw_answer": raw, "input_mode": "typed"},
            ).json()
            assert result["success"] is True

        unauthorized = client.get(f"/api/clinical/results/{session_id}")
        assert unauthorized.status_code == 401

        payload = client.get(
            f"/api/clinical/results/{session_id}",
            headers={"X-API-Key": "test-clinical-key"},
        ).json()
    finally:
        get_settings.cache_clear()

    assert payload["client"] == {"first_name": "Amy", "last_name": "Jones", "dob": "1980-01-05"}
    assert payload["selected_assessments"] == ["phq9"]
    assert payload["assessments"][0]["assessment_name"] == "PHQ-9"
    assert payload["assessments"][0]["score"]["total_score"] == 1
    assert len(payload["assessments"][0]["data"]) == 9


def test_clinical_results_api_omits_invalid_client_values(client, db, monkeypatch):
    import json

    from app.core.config import get_settings
    from app.db.models import FormAnswer

    monkeypatch.setenv("CLINICAL_RESULTS_API_KEYS", "test-clinical-key")
    get_settings.cache_clear()
    try:
        session = client.post(
            "/api/session/create",
            json={"form_id": "BH_SELF_REPORT_BATTERY", "manual_mode": True},
        ).json()
        session_id = session["session_id"]
        db.add(FormAnswer(
            session_id=session_id,
            field_key="client.first_name",
            value_json=json.dumps("what is your first name"),
            raw_answer="what is your first name",
            source="voice",
            confidence=1.0,
        ))
        db.commit()

        payload = client.get(
            f"/api/clinical/results/{session_id}",
            headers={"X-API-Key": "test-clinical-key"},
        ).json()
    finally:
        get_settings.cache_clear()

    assert payload["client"]["first_name"] is None


def test_medicaid_session_still_starts_without_clinical_gates(client):
    session = client.post(
        "/api/session/create",
        json={"form_id": "ODM_07216", "manual_mode": True},
    ).json()

    assert session["form_id"] == "ODM_07216"
    assert session["next_question"]["field_key"].startswith("applicant.")
    assert not any(key.startswith("selected.") for key in session["answers"])
