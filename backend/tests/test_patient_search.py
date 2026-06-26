"""Tests for patient search endpoint and masking."""

import pytest
from app.core.security import mask_name, mask_dob, mask_phone
from app.emr.mock_adapter import MockEMRAdapter


def test_mask_name():
    assert mask_name("John") == "J***"
    assert mask_name("A") == "A"
    assert mask_name("") == ""


def test_mask_dob():
    assert mask_dob("1990-01-15") == "****-**-15"
    assert mask_dob("") == ""


def test_mask_phone():
    assert mask_phone("6145551234") == "***-***-1234"
    assert mask_phone("") == ""


def test_mock_patient_search_found():
    adapter = MockEMRAdapter()
    results = adapter.search_patients("Test", "Patient", "1990-01-15")
    assert len(results) == 1
    assert results[0].external_patient_id == "mock-001"
    # 🔒 PHI is masked at the EMR search boundary (app/emr/masking.py): partial masks
    # let a user still recognize their own record without the backend exposing full PHI.
    assert results[0].first_name == "T***"        # mask_name("Test")
    assert results[0].dob == "****-**-15"          # mask_dob("1990-01-15")
    assert results[0].phone == "***-***-1234"      # mask_phone("6145551234")
    assert results[0].is_mock is True


def test_mock_patient_search_not_found():
    adapter = MockEMRAdapter()
    results = adapter.search_patients("Unknown", "Person", "2000-01-01")
    assert results == []


def test_mock_patient_search_partial_match():
    adapter = MockEMRAdapter()
    results = adapter.search_patients("Te", "Pa", "")
    assert len(results) >= 1


def test_patient_search_endpoint_missing_consent(client):
    response = client.post("/api/patient/search", json={
        "first_name": "Test",
        "last_name": "Patient",
        "dob": "1990-01-15",
        "consent": False,
    })
    assert response.status_code == 422


def test_patient_search_endpoint_success(client):
    response = client.post("/api/patient/search", json={
        "first_name": "Test",
        "last_name": "Patient",
        "dob": "1990-01-15",
        "consent": True,
    })
    assert response.status_code == 200
    data = response.json()
    assert data["count"] >= 1
    assert data["is_mock"] is True


def test_patient_search_endpoint_no_match(client):
    response = client.post("/api/patient/search", json={
        "first_name": "Nobody",
        "last_name": "Here",
        "dob": "2000-01-01",
        "consent": True,
    })
    assert response.status_code == 200
    assert response.json()["count"] == 0
