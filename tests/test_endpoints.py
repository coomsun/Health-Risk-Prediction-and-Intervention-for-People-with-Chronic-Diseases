"""9 个契约接口的取数与边界用例（空库 / 样例库 / 缺库）。"""

from __future__ import annotations

from tests.db_fixture import DISEASE_FIELDS


def _chronic_count(row: dict) -> int:
    return sum(int(row[field]) for field in DISEASE_FIELDS if row.get(field) is not None)


def _multimorbidity(row: dict) -> int:
    return 1 if _chronic_count(row) >= 2 else 0


def test_health_reports_db_rows(client, sample_db, rows):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0
    data = payload["data"]
    assert data["status"] == "ok"
    assert data["dbExists"] is True
    assert data["factRows"] == len(rows)
    assert "fact_brfss" in data["tables"]
    assert data["uptimeSeconds"] >= 0


def test_health_degrades_when_db_missing(client, missing_db):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0
    data = payload["data"]
    assert data["status"] == "degraded"
    assert data["dbExists"] is False
    assert data["factRows"] == 0
    assert data["detail"]


def test_query_endpoints_return_1003_when_db_missing(client, missing_db):
    response = client.get("/api/v1/overview")
    assert response.status_code == 503
    payload = response.json()
    assert payload["code"] == 1003
    assert "数据库未就绪" in payload["message"]


def test_overview_kpi_matches_fixture(client, sample_db, rows):
    data = client.get("/api/v1/overview").json()["data"]
    assert data["totalSamples"] == len(rows)
    assert data["yearSpan"]["min"] == min(r["year"] for r in rows)
    assert data["yearSpan"]["max"] == max(r["year"] for r in rows)
    assert data["yearSpan"]["years"] == len({r["year"] for r in rows})
    assert data["stateCount"] == len({r["state_fips"] for r in rows})
    assert data["chronicTypes"] == len(DISEASE_FIELDS)
    expected_cases = sum(_multimorbidity(r) for r in rows)
    assert data["multimorbidityCases"] == expected_cases
    assert data["multimorbidityRate"] == round(expected_cases / len(rows), 6)
    assert data["years"] and sum(y["samples"] for y in data["years"]) == len(rows)


def test_chronic_prevalence_with_filters(client, sample_db, rows):
    data = client.get("/api/v1/chronic/prevalence", params={"year": 2023, "state": 6}).json()["data"]
    subset = [r for r in rows if r["year"] == 2023 and r["state_fips"] == 6]
    assert data["totalSamples"] == len(subset)
    assert data["filters"] == {"year": 2023, "state": 6}
    assert len(data["items"]) == len(DISEASE_FIELDS)
    by_key = {item["key"]: item for item in data["items"]}
    assert by_key["diabetes"]["cases"] == sum(1 for r in subset if r["has_diabetes"] == 1)
    assert by_key["diabetes"]["prevalence"] == round(
        sum(1 for r in subset if r["has_diabetes"] == 1) / len(subset), 6
    )


def test_chronic_prevalence_all_sums_to_total(client, sample_db, rows):
    data = client.get("/api/v1/chronic/prevalence").json()["data"]
    assert data["totalSamples"] == len(rows)
    assert all(item["validSamples"] == len(rows) for item in data["items"])


def test_trend_series_one_point_per_year(client, sample_db, rows):
    data = client.get("/api/v1/trend", params={"metric": "multimorbidity_rate"}).json()["data"]
    years = sorted({r["year"] for r in rows})
    assert [point["year"] for point in data["series"]] == years
    for point in data["series"]:
        subset = [r for r in rows if r["year"] == point["year"]]
        expected = sum(_multimorbidity(r) for r in subset) / len(subset)
        assert point["value"] == round(expected, 6)
        assert point["denominator"] == len(subset)


def test_trend_supports_multiple_metrics(client, sample_db):
    for metric in ("total_samples", "chronic_avg", "obese_rate", "diabetes_rate"):
        payload = client.get("/api/v1/trend", params={"metric": metric}).json()
        assert payload["code"] == 0
        assert payload["data"]["metric"] == metric
        assert payload["data"]["series"]


def test_risk_factors_exposure_rates(client, sample_db, rows):
    data = client.get("/api/v1/risk/factors", params={"year": 2022}).json()["data"]
    subset = [r for r in rows if r["year"] == 2022]
    assert data["totalSamples"] == len(subset)
    by_key = {item["key"]: item for item in data["items"]}
    assert len(by_key) == 10
    expected_obese = sum(1 for r in subset if r["bmi"] >= 30)
    assert by_key["obese"]["exposed"] == expected_obese
    assert by_key["obese"]["rate"] == round(expected_obese / len(subset), 6)


def test_risk_stratify_distribution_consistent(client, sample_db, rows):
    data = client.get("/api/v1/risk/stratify").json()["data"]
    assert data["totalSamples"] == len(rows)
    assert sum(item["samples"] for item in data["distribution"]) == len(rows)
    assert sum(item["samples"] for item in data["levels"]) == len(rows)
    assert [level["level"] for level in data["levels"]] == ["低风险", "中风险", "高风险"]
    assert data["byAge"] and all("multimorbidityRate" in item for item in data["byAge"])


def test_geo_states_covers_all_states(client, sample_db, rows):
    data = client.get("/api/v1/geo/states", params={"metric": "diabetes_rate"}).json()["data"]
    states = {r["state_fips"] for r in rows}
    assert {item["stateFips"] for item in data["items"]} == states
    for item in data["items"]:
        subset = [r for r in rows if r["state_fips"] == item["stateFips"]]
        expected = sum(1 for r in subset if r["has_diabetes"] == 1) / len(subset)
        assert item["value"] == round(expected, 6)
        assert item["stateName"]


def test_model_metrics_empty_when_no_table_data(client, sample_db):
    payload = client.get("/api/v1/model/metrics").json()
    assert payload["code"] == 0
    assert payload["data"]["items"] == []
    assert payload["data"]["source"] == "none"


def test_empty_db_returns_empty_payloads_not_500(client, empty_db):
    overview = client.get("/api/v1/overview").json()
    assert overview["code"] == 0
    assert overview["data"]["totalSamples"] == 0

    prevalence = client.get("/api/v1/chronic/prevalence").json()
    assert prevalence["code"] == 0
    assert prevalence["data"]["items"] == []

    trend = client.get("/api/v1/trend").json()
    assert trend["code"] == 0
    assert trend["data"]["series"] == []

    factors = client.get("/api/v1/risk/factors").json()
    assert factors["code"] == 0
    assert factors["data"]["items"] == []

    stratify = client.get("/api/v1/risk/stratify").json()
    assert stratify["code"] == 0
    assert stratify["data"]["distribution"] == []

    geo = client.get("/api/v1/geo/states").json()
    assert geo["code"] == 0
    assert geo["data"]["items"] == []

    health = client.get("/api/v1/health").json()
    assert health["data"]["status"] == "ok"
    assert health["data"]["factRows"] == 0
