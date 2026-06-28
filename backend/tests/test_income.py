from app.ai.income import IncomeSource, aggregate_income, screen_income_sources


def test_aggregate_multiple_sources():
    sources = [
        IncomeSource(kind="wages", amount=500, frequency="weekly"),          # 500 * 52/12
        IncomeSource(kind="social_security", amount=1000, frequency="monthly"),
    ]
    agg = aggregate_income(sources)
    assert agg["monthly_total"] == 3166.67
    assert len(agg["resolved"]) == 2
    assert agg["unresolved"] == []


def test_hourly_wages_use_hours_per_week():
    sources = [IncomeSource(kind="wages", amount=20, frequency="hourly", hours_per_week=40)]
    agg = aggregate_income(sources)
    assert agg["monthly_total"] == 3466.67  # 20 * 40 = 800/wk -> 800 * 52/12


def test_unresolved_source_does_not_crash_or_count():
    sources = [
        IncomeSource(kind="wages", amount=1000, frequency="monthly"),
        IncomeSource(kind="other", amount=100, frequency="every_blue_moon"),  # unknown freq
        IncomeSource(kind="wages", amount=15, frequency="hourly"),            # missing hours
    ]
    agg = aggregate_income(sources)
    assert agg["monthly_total"] == 1000.0
    assert len(agg["unresolved"]) == 2


def test_screen_income_sources_combines_total_and_limit():
    sources = [IncomeSource(kind="wages", amount=5000, frequency="monthly")]
    result = screen_income_sources("adult_19_64", household_size=1, sources=sources)
    assert result["monthly_total"] == 5000.0
    assert result["screening_result"] == "above_limit"
    assert result["effective_date"] == "2026-03-01"
    assert "not a final eligibility decision" in result["caveat"].lower()


def test_screen_income_sources_tool_gated_to_odm():
    from app.ai.agent import _tools

    odm = {t["function"]["name"] for t in _tools("ODM_07216")}
    other = {t["function"]["name"] for t in _tools("SOME_OTHER_FORM")}
    assert "screen_income_sources" in odm
    assert "screen_income_sources" not in other


def test_exec_screen_income_sources_aggregates_and_screens():
    from app.ai.agent import _exec_screen_income_sources

    out = _exec_screen_income_sources({
        "category": "adult_19_64",
        "household_size": 1,
        "sources": [
            {"kind": "wages", "amount": 500, "frequency": "weekly"},
            {"kind": "social_security", "amount": 1000, "frequency": "monthly"},
        ],
    })
    assert out["monthly_total"] == 3166.67
    assert out["screening_result"] in {"above_limit", "at_or_below_limit"}


def test_exec_screen_income_sources_requires_sources():
    from app.ai.agent import _exec_screen_income_sources

    out = _exec_screen_income_sources({"category": "adult_19_64", "household_size": 1, "sources": []})
    assert out == {"ok": False, "error": "no_income_sources"}


def test_screen_income_sources_flags_incomplete_when_unresolved():
    sources = [
        IncomeSource(kind="wages", amount=2000, frequency="monthly"),
        IncomeSource(kind="wages", amount=15, frequency="hourly"),  # missing hours -> unresolved
    ]
    result = screen_income_sources("adult_19_64", household_size=1, sources=sources)
    assert result.get("incomplete") is True
    assert result["screening_result"] == "incomplete"
    assert len(result["unresolved"]) == 1


def test_odm_gate_prioritized_after_name():
    """Once the applicant's name is known, the next field front-loads the household gate."""
    from app.ai.agent import _prioritized_next

    missing = [
        {"field_key": "applicant.middle_name"},
        {"field_key": "applicant.suffix"},
        {"field_key": "person2.adding_person2"},
    ]
    answers = {"applicant.first_name": "Tony", "applicant.last_name": "Stark"}
    assert _prioritized_next("ODM_07216", answers, missing)["field_key"] == "person2.adding_person2"
    # Before the name is known, it stays in schema order.
    assert _prioritized_next("ODM_07216", {}, missing)["field_key"] == "applicant.middle_name"
    # Non-ODM forms are untouched.
    assert _prioritized_next("OTHER", answers, missing)["field_key"] == "applicant.middle_name"
