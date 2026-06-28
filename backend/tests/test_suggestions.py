from app.ai.suggestions import suggestions_for_field


def test_boolean_field_offers_yes_no():
    assert suggestions_for_field(None, {"field_key": "x.married", "type": "boolean"}) == ["Yes", "No"]


def test_select_field_offers_its_options():
    field = {"field_key": "person1.sex", "type": "select", "validation_rule": {"allowed_values": ["Male", "Female", "Other"]}}
    assert suggestions_for_field(None, field) == ["Male", "Female", "Other"]


def test_sensitive_text_field_has_no_suggestions():
    field = {"field_key": "person1.ssn", "type": "text", "sensitive": True}
    assert suggestions_for_field(None, field) == []


def test_plain_text_field_without_common_values_has_none():
    field = {"field_key": "applicant.first_name", "type": "text"}
    assert suggestions_for_field(None, field) == []


def test_city_field_includes_common_ohio_values(db):
    out = suggestions_for_field(db, {"field_key": "applicant.city", "type": "text"})
    assert "Columbus" in out  # common values seed it even before any history exists
