"""pytest 公共夹具。

原则：所有用例都跑在临时 SQLite 上，绝不读写交付库 db/chronic_risk.db，
也不依赖 artifacts/ 下是否存在真实模型文件。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import queries  # noqa: E402
from tests.db_fixture import create_db, sample_rows  # noqa: E402


def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """隔离缓存与产物目录，保证测试结果与真实环境无关。"""
    monkeypatch.setenv("API_CACHE_TTL", "0")
    monkeypatch.setattr(queries, "METRICS_DIR", tmp_path / "no_metrics_dir")


@pytest.fixture()
def sample_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """24 行确定性样例数据的库。"""
    db = create_db(tmp_path / "sample.db", sample_rows())
    monkeypatch.setenv("CHRONIC_RISK_DB", str(db))
    monkeypatch.setenv("CHRONIC_RISK_MODEL", str(tmp_path / "no_model" / "model.joblib"))
    _isolate(monkeypatch, tmp_path)
    return db


@pytest.fixture()
def empty_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """表结构齐全但没有数据的库（验证空结果不 500）。"""
    db = create_db(tmp_path / "empty.db")
    monkeypatch.setenv("CHRONIC_RISK_DB", str(db))
    monkeypatch.setenv("CHRONIC_RISK_MODEL", str(tmp_path / "no_model" / "model.joblib"))
    _isolate(monkeypatch, tmp_path)
    return db


@pytest.fixture()
def missing_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """库文件不存在（验证 /health 降级而不是崩溃）。"""
    db = tmp_path / "not_built" / "chronic_risk.db"
    monkeypatch.setenv("CHRONIC_RISK_DB", str(db))
    monkeypatch.setenv("CHRONIC_RISK_MODEL", str(tmp_path / "no_model" / "model.joblib"))
    _isolate(monkeypatch, tmp_path)
    return db


@pytest.fixture(scope="session")
def client():
    """FastAPI TestClient（进程内调用，不占端口）。"""
    from fastapi.testclient import TestClient

    from api.main import app

    return TestClient(app)


@pytest.fixture(scope="session")
def rows() -> list[dict]:
    """样例数据原文，供测试现场统计期望值。"""
    return sample_rows()


@pytest.fixture()
def auth_headers(client):
    """登录拿 JWT 令牌，供受保护接口（/predict）的用例复用。

    演示账号由 api.auth 的默认值提供（demo/demo12345）。
    若环境变量 AUTH_USERS 被改写，这里读的仍是模块默认值，
    因此测试与生产配置解耦。
    """
    resp = client.post("/api/v1/auth/login", json={"username": "demo", "password": "demo12345"})
    assert resp.status_code == 200, resp.text
    token = resp.json()["data"]["accessToken"]
    return {"Authorization": "Bearer " + token}
