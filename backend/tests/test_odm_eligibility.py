def test_odm_2026_income_screening_under_and_over_limit():
    from app.ai.odm_eligibility import screen_magi_income

    under = screen_magi_income("adult_19_64", household_size=3, monthly_income=3000)
    assert under["ok"] is True
    assert under["monthly_limit"] == 3028
    assert under["screening_result"] == "at_or_below_limit"
    assert "not a final eligibility decision" in under["caveat"].lower()

    over = screen_magi_income("adult_19_64", household_size=3, monthly_income=3300)
    assert over["ok"] is True
    assert over["monthly_limit"] == 3028
    assert over["screening_result"] == "above_limit"
    assert over["difference"] == 272


def test_odm_2026_income_screening_fails_closed_for_unknown_inputs():
    from app.ai.odm_eligibility import screen_magi_income

    bad_category = screen_magi_income("mystery", household_size=3, monthly_income=1000)
    assert bad_category["ok"] is False
    assert bad_category["error"] == "unknown_category"

    bad_size = screen_magi_income("pregnant", household_size=99, monthly_income=1000)
    assert bad_size["ok"] is False
    assert bad_size["error"] == "unsupported_household_size"


def test_agent_income_tool_rejects_non_numeric_values():
    from app.ai.agent import _exec_screen_income

    result = _exec_screen_income(
        {"category": "adult_19_64", "household_size": "three", "monthly_income": "a lot"}
    )
    assert result["ok"] is False
    assert result["error"] == "invalid_number"


def test_screen_magi_income_coerces_none_income_without_crashing():
    from app.ai.odm_eligibility import screen_magi_income

    # A None income must not raise; it screens as $0 (at or below the limit).
    result = screen_magi_income("adult_19_64", household_size=1, monthly_income=None)
    assert result["ok"] is True
    assert result["monthly_income"] == 0
    assert result["screening_result"] == "at_or_below_limit"


def test_monthly_from_pay_normalizes_common_frequencies():
    from app.ai.odm_eligibility import monthly_from_pay

    assert monthly_from_pay(600, "weekly")["monthly_income"] == 2600.0
    assert monthly_from_pay(1200, "every two weeks")["monthly_income"] == 2600.0
    assert monthly_from_pay(1300, "twice a month")["monthly_income"] == 2600.0
    assert monthly_from_pay(2600, "monthly")["monthly_income"] == 2600.0
    assert monthly_from_pay(31200, "yearly")["monthly_income"] == 2600.0
    # Fails closed on an unrecognized frequency or bad amount.
    assert monthly_from_pay(600, "per fortnight-ish")["ok"] is False
    assert monthly_from_pay("lots", "weekly")["ok"] is False


def test_income_tool_converts_pay_frequency_to_monthly():
    from app.ai.agent import _exec_screen_income

    # $600/week for a household of 3, adult category -> ~$2,600/mo, at/below the $3,028 limit.
    result = _exec_screen_income({
        "category": "adult_19_64", "household_size": 3,
        "monthly_income": 600, "pay_frequency": "weekly",
    })
    assert result["ok"] is True
    assert result["monthly_income"] == 2600.0
    assert result["screening_result"] == "at_or_below_limit"
    assert result["income_normalized_from"]["frequency"] == "weekly"


def test_screen_income_tool_is_gated_to_ohio_medicaid_forms():
    from app.ai.agent import _tools

    odm = {t["function"]["name"] for t in _tools("ODM_07216")}
    other = {t["function"]["name"] for t in _tools("SOME_OTHER_FORM")}
    assert "screen_income" in odm
    assert "screen_income" not in other
    # Core tools are always present.
    assert {"save_answers", "skip_fields", "go_to_review"} <= other
