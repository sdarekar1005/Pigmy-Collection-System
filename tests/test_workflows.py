import os
from datetime import date

import pytest

from app import create_app


@pytest.fixture
def client():
    os.environ["DEV_AGENT_PASSWORD"] = "Password123!"
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.test_client() as client:
        client.post("/api/setup", json={"name": "Test Agent", "agent_id": "AGENT001", "mobile": "9999999999", "email": "test@example.com", "password": "Password123!", "confirm_password": "Password123!"})
        yield client


def login(client):
    response = client.post("/api/login", json={"username": "agent001", "password": "Password123!"})
    assert response.status_code == 200


def create_customer(client, customer_id="CUS001"):
    response = client.post(
        "/api/customers",
        json={
            "customer_id": customer_id,
            "name": "Test Customer",
            "mobile": "9876543210",
            "address": "Test address",
            "daily_amount": "100",
            "collection_frequency": "daily",
        },
    )
    assert response.status_code == 201
    return response.get_json()["data"]["customer"]


def test_dashboard_starts_with_legitimate_zero_state(client):
    login(client)
    data = client.get("/api/dashboard").get_json()["data"]["summary"]
    assert data["today_collection"] == 0
    assert data["daily_target"] == 0
    assert data["customers_collected"] == 0
    assert data["pending_customers"] == 0


def test_collection_updates_partial_dashboard_and_pending_state(client):
    login(client)
    customer = create_customer(client)
    response = client.post(
        "/api/collections",
        json={"customer_id": customer["id"], "amount": "40", "collection_date": date.today().isoformat(), "reference_number": "REF-1", "notes": "Part payment"},
    )
    assert response.status_code == 201
    assert response.get_json()["data"]["collection"]["notes"] == "Part payment"

    dashboard = client.get("/api/dashboard").get_json()["data"]["summary"]
    assert dashboard["today_collection"] == 40
    assert dashboard["daily_target"] == 100
    assert dashboard["customers_collected"] == 1
    assert dashboard["pending_customers"] == 1
    assert dashboard["pending_amount"] == 60
    assert dashboard["collection_progress"] == 40

    pending = client.get("/api/pending").get_json()["data"]
    assert pending["pending"][0]["collection_status"] == "partial"
    assert pending["pending"][0]["due_amount"] == 60


def test_end_of_day_pdf_and_profile_update_use_real_data(client):
    login(client)
    customer = create_customer(client, "CUS002")
    client.post("/api/collections", json={"customer_id": customer["id"], "amount": "100"})

    summary = client.get("/api/end-of-day").get_json()["data"]
    assert summary["expected_collection"] == 100
    assert summary["total_collection"] == 100
    assert summary["pending_customers"] == 0
    assert len(summary["transactions_detail"]) == 1

    pdf = client.get("/api/end-of-day/pdf")
    assert pdf.status_code == 200
    assert pdf.mimetype == "application/pdf"
    assert pdf.data.startswith(b"%PDF")

    profile = client.put("/api/agent-profile", json={"name": "Updated Agent", "mobile": "9999999999"})
    assert profile.status_code == 200
    assert profile.get_json()["data"]["agent"]["name"] == "Updated Agent"


def test_customer_delete_requires_inactive_status_and_preserves_history(client):
    login(client)
    customer = create_customer(client, "CUS003")
    client.post("/api/collections", json={"customer_id": customer["id"], "amount": "100"})
    active_delete = client.delete(f"/api/customers/{customer['id']}", json={"confirmation": "DELETE", "current_password": "Password123!"})
    assert active_delete.status_code == 400
    client.put(f"/api/customers/{customer['id']}", json={"status": "inactive"})
    deleted = client.delete(f"/api/customers/{customer['id']}", json={"confirmation": "DELETE", "current_password": "Password123!"})
    assert deleted.status_code == 200
    assert client.get("/api/customers").get_json()["data"]["customers"] == []
    history = client.get("/api/collections").get_json()["data"]["collections"]
    assert len(history) == 1
    assert history[0]["customer_code"] == "CUS003"


def test_inactive_customer_is_excluded_from_expected_but_keeps_todays_collection(client):
    login(client)
    customer = create_customer(client, "CUS004")
    created = client.post("/api/collections", json={"customer_id": customer["id"], "amount": "100"})
    assert created.status_code == 201
    client.put(f"/api/customers/{customer['id']}", json={"status": "inactive"})
    summary = client.get("/api/dashboard").get_json()["data"]["summary"]
    assert summary["daily_target"] == 0
    assert summary["pending_customers"] == 0
    assert summary["today_collection"] == 100
    assert summary["customers_collected"] == 1
    assert len(client.get("/api/collections").get_json()["data"]["collections"]) == 1
