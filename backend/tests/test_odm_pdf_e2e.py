"""End-to-end regression for the real Ohio Medicaid ODM 07216 PDF flow."""

from __future__ import annotations

from pathlib import Path

import fitz


ODM_REQUIRED_ANSWERS = {
    "applicant.first_name": "Alice",
    "applicant.last_name": "Smith",
    "applicant.zip": "43215",
    "applicant.is_homeless": "no",
    "applicant.home_address": "100 Main St",
    "applicant.city": "Columbus",
    "applicant.state": "OH",
    "applicant.phone": "6145551234",
    "person1.first_name": "Alice",
    "person1.last_name": "Smith",
    "person1.relationship_to_applicant": "Self",
    "person1.dob": "01/15/1985",
    "person1.sex": "Female",
    "person1.tax_file_next_year": "no",
    "person1.claimed_as_dependent": "no",
    "person1.married": "no",
    "person1.wants_health_coverage": "yes",
    "person1.us_citizen_or_national": "yes",
    "person2.adding_person2": "no",
    "income.has_employment": "not_employed",
    "review.acknowledgement": "yes",
    "review.signature_name": "Alice Smith",
    "review.signature_date": "06/26/2026",
}


def _complete_minimal_odm_session(client) -> str:
    response = client.post("/api/session/create", json={"form_id": "ODM_07216", "manual_mode": True})
    assert response.status_code == 200, response.text
    session_id = response.json()["session_id"]

    for _ in range(300):
        state = client.get(f"/api/session/{session_id}").json()
        next_question = state["next_question"]
        if next_question is None:
            assert state["status"] == "ready_for_review"
            return session_id

        field_key = next_question["field_key"]
        if field_key in ODM_REQUIRED_ANSWERS:
            answer = client.post(
                f"/api/session/{session_id}/answer",
                json={
                    "field_key": field_key,
                    "raw_answer": ODM_REQUIRED_ANSWERS[field_key],
                    "input_mode": "typed",
                },
            )
            assert answer.status_code == 200, answer.text
            payload = answer.json()
            assert payload["success"] is True, payload
            continue

        assert next_question["is_optional"] is True, f"Missing required test answer for {field_key}"
        skipped = client.post(
            f"/api/session/{session_id}/skip",
            json={"field_key": field_key, "raw_answer": "skip", "input_mode": "typed"},
        )
        assert skipped.status_code == 200, skipped.text
        assert skipped.json()["success"] is True, skipped.json()

    raise AssertionError("ODM session did not reach review within 300 steps")


def _widget_values(pdf_path: Path) -> dict[str, list[str]]:
    doc = fitz.open(str(pdf_path))
    try:
        values: dict[str, list[str]] = {}
        for page in doc:
            for widget in page.widgets() or []:
                if widget.field_name:
                    values.setdefault(widget.field_name, []).append(widget.field_value)
        return values
    finally:
        doc.close()


def test_odm_session_approval_generates_filled_official_pdf(client, tmp_path, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("PDF_OUTPUT_DIR", str(tmp_path))
    get_settings.cache_clear()

    session_id = _complete_minimal_odm_session(client)
    approved = client.post(f"/api/session/{session_id}/approve", json={"approved_by": "patient"})
    assert approved.status_code == 200, approved.text

    workflow = approved.json()
    assert workflow["status"] == "completed"
    task = workflow["tasks"][0]
    assert task["type"] == "generate_pdf"
    assert task["status"] == "completed"
    assert task["output"]["is_fallback"] is False

    downloaded = client.get(task["output"]["download_url"])
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.headers["content-type"] == "application/pdf"

    pdf_path = tmp_path / task["output"]["file_name"]
    pdf_path.write_bytes(downloaded.content)
    values = _widget_values(pdf_path)

    assert values["1 First name"] == ["Alice"]
    assert values["Last name"] == ["Smith"]
    assert values["2 Home address Check here if you are Homeless"] == ["100 Main St"]
    assert values["4 City"] == ["Columbus"]
    assert values["5 State"] == ["OH"]
    assert values["6 Zip code"] == ["43215"]
    assert values["14 Phone number"] == ["6145551234"]
    assert values["First Name"] == ["Alice"]
    assert values["Last name_2"] == ["Smith"]
    assert values["3 Date of birth mmddyyyy"] == ["01/15/1985"]
    assert values["undefined_5"] == ["On"]
    assert values["No Skip to question c"] == ["On"]
    assert "No_3" in values["c Will you be claimed as a dependent on someone elses tax return"]
    assert values["undefined_7"] == ["On"]
    assert values["Yes Answer questions 923"] == ["On"]
    assert "Yes_6" in values["14 Are you a US citizen or US national"]
    assert values["undefined_39"] == ["On"]
    assert values["Date mmddyyyy"] == ["06/26/2026"]

    # This optional yes/no field was skipped by the flow; a skip must remain blank
    # in the PDF instead of being treated as a false "No" answer.
    assert values["undefined_9"] == [""]

    doc = fitz.open(str(pdf_path))
    try:
        assert "Alice Smith" in doc[12].get_text()
    finally:
        doc.close()
        get_settings.cache_clear()


def test_odm_optional_branch_mappings_fill_real_pdf_widgets(tmp_path, monkeypatch):
    from app.core.config import get_settings
    from app.forms.service import load_form_schema
    from app.pdf.pdf_service import _fill_acroform_pdf, _get_base_pdf_path

    monkeypatch.setenv("PDF_OUTPUT_DIR", str(tmp_path))
    get_settings.cache_clear()

    base_pdf = _get_base_pdf_path("ODM_07216")
    assert base_pdf is not None

    answers = {
        "person1.recent_pregnancy_babies_expected": 2,
        "person1.naturalized_or_derived_citizen": True,
        "person1.received_benefits_other_state": True,
        "person1.benefits_other_state_where": "KY",
        "person2.foster_care_after_18": False,
        "person2.incarcerated": False,
        "person2.served_military": False,
        "person2.received_benefits_other_state": True,
        "person2.benefits_other_state_where": "IN",
        "income.has_self_employment": True,
        "income.emp3_person": "Alice Smith",
        "income.emp3_employer": "Acme Store",
        "income.emp3_gross_wages": "500",
        "income.emp3_frequency": "Weekly",
        "income.emp4_person": "Bob Smith",
        "income.emp4_employer": "Beta Cafe",
        "income.emp4_gross_wages": "250",
        "income.emp4_frequency": "Monthly",
        "income.expense_other_deductions": "Student loan interest 50",
        "ai_an.person1_is_ai_an": True,
        "ai_an.person1_tribal_name": "Shawnee",
        "ai_an.person2_is_ai_an": False,
        "health_coverage.person1_has_employer_insurance": True,
        "health_coverage.job_offered_coverage_anyone": True,
        "health_coverage.job_offered_person_name": "Alice Smith",
        "health_coverage.job_offered_employer_name": "Acme Store",
    }
    out_path, _ = _fill_acroform_pdf(
        "optional-branch-session",
        answers,
        base_pdf,
        "ODM_07216",
        load_form_schema("ODM_07216"),
    )
    values = _widget_values(out_path)

    assert values["How many babies expected2"] == ["2"]
    assert "4" in values["22 Is this person currently receiving or has this person ever received benefits in another state"]
    assert values["undefined_14"] == ["On"]
    assert values["21 Are you currently or did you previously receive benefits in another state Yes No If yes where"] == ["KY"]
    assert "No_22" in values["19 Was PERSON 2 in foster care at age 18 or older"]
    assert "No_23" in values["20 Is PERSON 2 currently incarcerated detained or jailed"]
    assert values["undefined_35"] == ["On"]
    assert "Yes_23" in values["22 Is PERSON 2 currently receiving or has PERSON ever received benefits in another state"]
    assert values["If yes where"] == ["IN"]
    assert values["undefined_38"] == ["On"]
    assert values["PersonRow3"] == ["Alice Smith"]
    assert values["Employer Name and AddressRow3"] == ["Acme Store"]
    assert values["Gross Income Before Taxes per Pay PeriodRow3"] == ["500"]
    assert values["How Often weekly biweekly monthlyRow3"] == ["Weekly"]
    assert values["PersonRow4"] == ["Bob Smith"]
    assert values["Other Type Expenses"] == ["Student loan interest 50"]
    assert "Yes_29" in values["undefined_52"]
    assert values["If yes tribe name"] == ["Shawnee"]
    assert "No_31" in values["undefined_53"]
    assert values["undefined_42"] == ["On"]
    assert values["Employer Insurance"] == ["Person 1"]
    assert values["Yes You will also need to complete and include APPENDIX A"] == ["On"]
    assert values["1 Employee Name First Name Middle Name Last Name"] == ["Alice Smith"]
    assert values["NameRow1"] == ["Alice Smith"]
    assert values["4 EmployerCompany Name"] == ["Acme Store"]

    get_settings.cache_clear()
