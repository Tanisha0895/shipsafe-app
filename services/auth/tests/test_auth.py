import pytest
from fastapi.testclient import TestClient

from app.main import app

CREDS = {"email": "alice@test.dev", "password": "secret123"}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_register_then_duplicate(client):
    assert client.post("/register", json=CREDS).status_code == 201
    assert client.post("/register", json=CREDS).status_code == 409


def test_login_and_me(client):
    r = client.post("/login", json=CREDS)
    assert r.status_code == 200
    token = r.json()["access_token"]
    me = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == CREDS["email"]


def test_wrong_password(client):
    r = client.post("/login", json={"email": CREDS["email"], "password": "wrong"})
    assert r.status_code == 401


def test_me_requires_valid_token(client):
    assert client.get("/me").status_code == 401
    assert client.get("/me", headers={"Authorization": "Bearer not-a-token"}).status_code == 401