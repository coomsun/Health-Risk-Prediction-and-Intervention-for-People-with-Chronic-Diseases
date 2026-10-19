# -*- coding: utf-8 -*-
"""test_auth.py — JWT 鉴权测试（综合项目加分项）

覆盖：
  1. 未带令牌访问受保护接口 -> 401
  2. 错误密码登录 -> 401
  3. 正确登录 -> 拿到令牌
  4. 带令牌访问受保护接口 -> 200
  5. 伪造/篡改令牌 -> 401
  6. 公开查询接口无需令牌 -> 200
"""
import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _login(client, username="demo", password="demo12345"):
    return client.post("/api/v1/auth/login", json={"username": username, "password": password})


def test_predict_without_token_returns_401(client):
    r = client.post("/api/v1/predict", json={"age": 68})
    assert r.status_code == 401
    body = r.json()
    assert body["code"] != 0
    assert "令牌" in body["message"]


def test_login_wrong_password_returns_401(client):
    r = _login(client, password="definitely-wrong")
    assert r.status_code == 401
    assert r.json()["code"] != 0


def test_login_success_returns_token(client):
    r = _login(client)
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["tokenType"] == "Bearer"
    assert data["expiresIn"] > 0
    assert len(data["accessToken"]) > 40


def test_predict_with_valid_token_ok(client):
    token = _login(client).json()["data"]["accessToken"]
    r = client.post(
        "/api/v1/predict",
        json={"age": 68, "sex": 1, "bmi": 31.5, "smoker3": 1, "phys_activity": 0},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert 0.0 <= body["data"]["probability"] <= 1.0


def test_predict_with_tampered_token_returns_401(client):
    r = client.post(
        "/api/v1/predict",
        json={"age": 68},
        headers={"Authorization": "Bearer not.a.real.token"},
    )
    assert r.status_code == 401
    assert r.json()["code"] != 0


def test_whoami_requires_token(client):
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401

    token = _login(client).json()["data"]["accessToken"]
    r2 = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 200
    assert r2.json()["data"]["username"] == "demo"


@pytest.mark.parametrize("path", [
    "/api/v1/health",
    "/api/v1/overview",
    "/api/v1/chronic/prevalence",
    "/api/v1/trend",
])
def test_public_endpoints_need_no_token(client, path):
    """查询类接口保持公开，评阅人无需登录即可演示。"""
    r = client.get(path)
    assert r.status_code == 200
    assert r.json()["code"] == 0
