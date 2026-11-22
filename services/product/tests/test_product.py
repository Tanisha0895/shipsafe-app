import pytest
from fastapi.testclient import TestClient

from app.main import app

KEY = {"X-Internal-Key": "test-key"}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    assert client.get("/health").status_code == 200


def test_list_works_without_redis(client):
    r = client.get("/products")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "database"
    assert len(body["items"]) == 4


def test_unknown_product_is_404(client):
    assert client.get("/products/999").status_code == 404


def test_reserve_requires_internal_key(client):
    r = client.post("/products/1/reserve", json={"quantity": 1})
    assert r.status_code == 403


def test_reserve_reduces_stock(client):
    before = client.get("/products/1").json()["stock"]
    r = client.post("/products/1/reserve", json={"quantity": 2}, headers=KEY)
    assert r.status_code == 200
    assert r.json()["stock"] == before - 2


def test_reserve_more_than_stock_is_409(client):
    r = client.post("/products/1/reserve", json={"quantity": 100000}, headers=KEY)
    assert r.status_code == 409