"""POST /api/v1/predict 用例：模型缺失、参数校验、真实模型推理。"""

from __future__ import annotations

from pathlib import Path

import pytest

FEATURES = ["bmi", "smoker3", "age_grp"]


def test_predict_without_model_returns_1001(client, sample_db):
    response = client.post("/api/v1/predict", json={"bmi": 28.5})
    assert response.status_code == 503
    payload = response.json()
    assert payload["code"] == 1001
    assert payload["message"] == "模型未就绪"
    assert payload["data"]["modelPath"]


def test_predict_empty_body_returns_400(client, sample_db):
    response = client.post("/api/v1/predict", json={})
    assert response.status_code == 400
    payload = response.json()
    assert payload["code"] == 400
    assert "至少提供一项特征" in payload["message"]


def test_predict_invalid_field_returns_400(client, sample_db):
    response = client.post("/api/v1/predict", json={"bmi": 999})
    assert response.status_code == 400
    payload = response.json()
    assert payload["code"] == 400
    assert "bmi" in payload["message"]


def test_predict_unknown_field_is_ignored(client, sample_db):
    response = client.post("/api/v1/predict", json={"bmi": 26.0, "unknown_field": 1})
    # 未知字段被忽略，因此命中"模型未就绪"而不是参数错误
    assert response.json()["code"] == 1001


@pytest.fixture()
def trained_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """现场训练一个支持缺失值的真实模型（HistGradientBoosting），不虚构任何输出。"""
    pd = pytest.importorskip("pandas")
    numpy = pytest.importorskip("numpy")
    joblib = pytest.importorskip("joblib")
    from sklearn.ensemble import HistGradientBoostingClassifier

    rng = numpy.random.default_rng(2024)
    frame = pd.DataFrame(
        {
            "bmi": rng.uniform(18.0, 42.0, 300),
            "smoker3": rng.integers(1, 5, 300),
            "age_grp": rng.integers(1, 14, 300),
        }
    )
    labels = ((frame["bmi"] > 30) | (frame["smoker3"] == 1) | (frame["age_grp"] >= 10)).astype(int)
    model = HistGradientBoostingClassifier(max_iter=40, random_state=0).fit(frame, labels.to_numpy())
    path = tmp_path / "model" / "model.joblib"
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, path)
    assert not model.__dict__.get("_sidecar", None)
    monkeypatch.setenv("CHRONIC_RISK_MODEL", str(path))
    monkeypatch.setenv("API_CACHE_TTL", "0")
    return path


def test_predict_with_real_model(client, trained_model):
    response = client.post("/api/v1/predict", json={"bmi": 35.0, "smoker3": 1, "age_grp": 8})
    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0
    data = payload["data"]
    assert 0.0 <= data["probability"] <= 1.0
    assert data["prediction"] in (0, 1)
    assert data["riskLevel"] in {"低风险", "中风险", "高风险"}
    assert data["model"]["featureNames"] == FEATURES
    assert data["missingFeatures"] == []
    assert data["latencyMs"] >= 0
    thresholds = data["thresholds"]
    expected_level = (
        "高风险"
        if data["probability"] >= thresholds["high"]
        else ("中风险" if data["probability"] >= thresholds["low"] else "低风险")
    )
    assert data["riskLevel"] == expected_level


def test_predict_partial_features_are_reported(client, trained_model):
    response = client.post("/api/v1/predict", json={"bmi": 24.0})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["missingFeatures"] == ["smoker3", "age_grp"]
    assert 0.0 <= data["probability"] <= 1.0


def test_predict_high_risk_has_higher_probability_than_low_risk(client, trained_model):
    low = client.post("/api/v1/predict", json={"bmi": 20.0, "smoker3": 4, "age_grp": 2}).json()["data"]
    high = client.post("/api/v1/predict", json={"bmi": 40.0, "smoker3": 1, "age_grp": 12}).json()["data"]
    assert high["probability"] > low["probability"]
