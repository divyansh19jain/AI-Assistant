from app.ai.household import HouseholdMember, household_size, to_odm_field_values
from app.sessions import service as svc


def test_household_size_counts_tax_unit():
    members = [
        HouseholdMember(first_name="Tony", relationship="self"),
        HouseholdMember(first_name="Pepper", relationship="spouse"),
        HouseholdMember(first_name="Kid", relationship="child", is_tax_dependent=True),
        HouseholdMember(first_name="Roommate", relationship="other"),  # not in tax unit
    ]
    assert household_size(members) == 3


def test_household_size_minimum_is_one():
    assert household_size([]) == 1


def test_to_odm_field_values_maps_self_and_person2():
    members = [
        HouseholdMember(first_name="Tony", last_name="Stark", relationship="self"),
        HouseholdMember(first_name="Pepper", last_name="Potts", relationship="spouse",
                        applying=True, dob="01/15/1985", sex="Female"),
    ]
    values = to_odm_field_values(members)
    assert values["applicant.first_name"] == "Tony"
    assert values["person2.adding_person2"] is True
    assert values["person2.first_name"] == "Pepper"
    assert values["person2.relationship_to_applicant"] == "Spouse"
    assert values["person2.sex"] == "Female"
    # Gate must come before its dependent fields (so invalidation can't clear them).
    keys = list(values)
    assert keys.index("person2.adding_person2") < keys.index("person2.first_name")


def test_non_applying_other_member_does_not_open_person2():
    members = [
        HouseholdMember(first_name="Tony", relationship="self"),
        HouseholdMember(first_name="Cousin", relationship="other", applying=False),
    ]
    values = to_odm_field_values(members)
    assert "person2.adding_person2" not in values


def test_apply_household_endpoint_populates_session(client):
    sid = client.post("/api/session/create", json={"form_id": "ODM_07216", "manual_mode": True}).json()["session_id"]
    r = client.post(f"/api/session/{sid}/household", json={"members": [
        {"first_name": "Tony", "last_name": "Stark", "relationship": "self"},
        {"first_name": "Pepper", "last_name": "Potts", "relationship": "spouse",
         "applying": True, "dob": "01/15/1985", "sex": "Female"},
    ]})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["household_size"] == 2
    assert "person2.adding_person2" in data["applied"]
    assert data["errors"] == []


def test_applied_person2_survives_invalidation(client, db):
    """Because the gate is applied first, the Person 2 details stay applicable and
    are not wiped by correction-aware invalidation."""
    sid = client.post("/api/session/create", json={"form_id": "ODM_07216", "manual_mode": True}).json()["session_id"]
    client.post(f"/api/session/{sid}/household", json={"members": [
        {"first_name": "Tony", "relationship": "self"},
        {"first_name": "Pepper", "last_name": "Potts", "relationship": "spouse", "applying": True},
    ]})
    answers = svc._answers_map(db, sid)
    assert answers.get("person2.adding_person2") is True
    assert answers.get("person2.first_name") == "Pepper"
