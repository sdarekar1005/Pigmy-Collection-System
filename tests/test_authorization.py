import os

import pytest

from app import create_app


@pytest.fixture
def client():
    os.environ["DEV_AGENT_PASSWORD"] = "Password123!"
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.test_client() as client:
        client.post("/api/setup", json={"name": "Test Agent", "agent_id": "AGENT001", "mobile": "9999999999", "email": "test@example.com", "password": "Password123!", "confirm_password": "Password123!"})
        with app.app_context():
            app.db.create_all()
        yield client


def test_unauthorized_access_requires_login(client):
    response = client.get("/api/me")
    assert response.status_code == 401


def test_agent_cannot_access_admin_only_data(client):
    client.post("/api/login", json={"username": "agent001", "password": "Password123!"})
    response = client.get("/api/admin/overview")
    assert response.status_code == 403
