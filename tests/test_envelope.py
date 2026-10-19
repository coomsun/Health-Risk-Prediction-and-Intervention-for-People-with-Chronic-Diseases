"""信封结构、耗时头、错误处理与路由注册的用例。"""

from __future__ import annotations

from typing import Any

import pytest

ENVELOPE_KEYS = {"code", "message", "data", "traceId", "timestamp"}


def _check_envelope(payload: dict[str, Any]) -> None:
    assert set(payload) == ENVELOPE_KEYS, payload
    assert payload["traceId"]
    assert isinstance(payload["timestamp"], int)
    assert payload["timestamp"] > 1_600_000_000_000


def test_envelope_structure_and_timing_header(client, sample_db):
    response = client.get("/api/v1/overview")
    assert response.status_code == 200
    payload = response.json()
    _check_envelope(payload)
    assert payload["code"] == 0
    assert payload["message"] == "ok"
    assert isinstance(payload["data"], dict)

    # 耗时头：数值毫秒，且与信封 traceId 对齐
    elapsed = response.headers["X-Response-Time"]
    assert float(elapsed) >= 0.0
    assert response.headers["X-Trace-Id"] == payload["traceId"]


def test_trace_id_is_echoed_when_client_provides_one(client, sample_db):
    response = client.get("/api/v1/overview", headers={"X-Trace-Id": "trace-from-client"})
    assert response.json()["traceId"] == "trace-from-client"
    assert response.headers["X-Trace-Id"] == "trace-from-client"


def test_openapi_registers_nine_contract_paths(client):
    spec = client.get("/openapi.json").json()
    paths = spec["paths"]
    expected = {
        "/api/v1/health",
        "/api/v1/overview",
        "/api/v1/chronic/prevalence",
        "/api/v1/trend",
        "/api/v1/risk/factors",
        "/api/v1/risk/stratify",
        "/api/v1/geo/states",
        "/api/v1/model/metrics",
        "/api/v1/predict",
    }
    assert expected <= set(paths)
    assert "get" in paths["/api/v1/health"]
    assert "post" in paths["/api/v1/predict"]
    assert len([p for p in paths if p.startswith("/api/v1/")]) == 9


def test_unknown_path_returns_envelope_404(client, sample_db):
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    payload = response.json()
    _check_envelope(payload)
    assert payload["code"] == 404
    assert payload["message"]
    assert "X-Response-Time" in response.headers


def test_invalid_query_param_returns_code_400(client, sample_db):
    response = client.get("/api/v1/chronic/prevalence", params={"year": 1800})
    assert response.status_code == 400
    payload = response.json()
    _check_envelope(payload)
    assert payload["code"] == 400
    assert "参数校验失败" in payload["message"]
    assert payload["data"]["errors"]


def test_invalid_metric_returns_allowed_list(client, sample_db):
    response = client.get("/api/v1/trend", params={"metric": "not_a_metric"})
    assert response.status_code == 400
    payload = response.json()
    assert payload["code"] == 400
    assert "可选值" in payload["message"]
    assert "multimorbidity_rate" in payload["data"]["allowed"]


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/docs",
        "/openapi.json",
    ],
)
def test_docs_entrypoints_served(client, path):
    assert client.get(path).status_code == 200
