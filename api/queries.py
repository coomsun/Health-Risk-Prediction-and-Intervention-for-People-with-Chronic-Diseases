"""SQLite 只读聚合查询层。

设计约定
--------
1. **数字全部来自 SQL**：本模块不出现任何硬编码统计量，患病率/暴露率/共病率
   等均由 fact_brfss 聚合得出；Python 侧只做除法与四舍五入。
2. **参数化防注入**：所有 SQL 用 ? 占位符传参；列名/指标名一律取自本模块的
   白名单映射（TREND_METRICS / RISK_FACTORS），从不拼接用户输入。
3. **只读连接**：数据库以 mode=ro URI 打开并设置 PRAGMA query_only=ON，
   服务进程无法写入，杜绝误改生产库。
4. **缺库/缺列降级**：数据库尚未构建或列名不一致时返回空数组或零值，
   由接口层返回 code=0 的空结果，而不是 500。

数据库结构以 _设计规格.md 第 4 节为准（fact_brfss + dim_* + agg_* +
model_metrics + audit_pipeline）。
"""

from __future__ import annotations

import contextlib
import copy
import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence

from .contract import CODE_DB_UNAVAILABLE, CODE_INVALID_PARAM, ApiError

# ---------------------------------------------------------------- 常量与路径
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "db" / "chronic_risk.db"
MODEL_DIR = PROJECT_ROOT / "artifacts" / "model"
METRICS_DIR = PROJECT_ROOT / "artifacts" / "metrics"

DB_ENV = "CHRONIC_RISK_DB"
MODEL_ENV = "CHRONIC_RISK_MODEL"
CACHE_ENV = "API_CACHE_TTL"

FACT_TABLE = "fact_brfss"
MODEL_TABLE = "model_metrics"

#: 八种慢性病标志位（字段名冻结于 _设计规格.md 第 2 节）
DISEASES: tuple[tuple[str, str, str], ...] = (
    ("has_diabetes", "diabetes", "糖尿病"),
    ("has_mi", "mi", "心肌梗死"),
    ("has_chd", "chd", "冠心病"),
    ("has_stroke", "stroke", "卒中"),
    ("has_copd", "copd", "慢阻肺"),
    ("has_asthma", "asthma", "哮喘"),
    ("has_kidney", "kidney", "慢性肾病"),
    ("has_depression", "depression", "抑郁"),
)

#: _AGEG5YR 编码 → 年龄段标签（参考字典，非统计量）
AGE_GROUP_LABELS: dict[int, str] = {
    1: "18-24",
    2: "25-29",
    3: "30-34",
    4: "35-39",
    5: "40-44",
    6: "45-49",
    7: "50-54",
    8: "55-59",
    9: "60-64",
    10: "65-69",
    11: "70-74",
    12: "75-79",
    13: "80+",
}

#: _STATE (FIPS) → 州/属地名称（参考字典，非统计量；dim_state 存在时优先用库内名称）
STATE_FIPS_NAMES: dict[int, str] = {
    1: "Alabama", 2: "Alaska", 4: "Arizona", 5: "Arkansas", 6: "California",
    8: "Colorado", 9: "Connecticut", 10: "Delaware", 11: "District of Columbia",
    12: "Florida", 13: "Georgia", 15: "Hawaii", 16: "Idaho", 17: "Illinois",
    18: "Indiana", 19: "Iowa", 20: "Kansas", 21: "Kentucky", 22: "Louisiana",
    23: "Maine", 24: "Maryland", 25: "Massachusetts", 26: "Michigan",
    27: "Minnesota", 28: "Mississippi", 29: "Missouri", 30: "Montana",
    31: "Nebraska", 32: "Nevada", 33: "New Hampshire", 34: "New Jersey",
    35: "New Mexico", 36: "New York", 37: "North Carolina", 38: "North Dakota",
    39: "Ohio", 40: "Oklahoma", 41: "Oregon", 42: "Pennsylvania",
    44: "Rhode Island", 45: "South Carolina", 46: "South Dakota",
    47: "Tennessee", 48: "Texas", 49: "Utah", 50: "Vermont", 51: "Virginia",
    53: "Washington", 54: "West Virginia", 55: "Wisconsin", 56: "Wyoming",
    66: "Guam", 72: "Puerto Rico", 78: "Virgin Islands",
}


def db_path() -> Path:
    """当前使用的 SQLite 路径（环境变量 CHRONIC_RISK_DB 可覆盖，测试用）。"""
    raw = os.environ.get(DB_ENV)
    return Path(raw).expanduser().resolve() if raw else DEFAULT_DB_PATH


def model_path() -> Path:
    """在线预测模型路径（环境变量 CHRONIC_RISK_MODEL 可覆盖，测试用）。"""
    raw = os.environ.get(MODEL_ENV)
    if raw:
        return Path(raw).expanduser().resolve()
    return MODEL_DIR / "model.joblib"


# ---------------------------------------------------------------- 只读连接
@contextlib.contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    """打开只读连接；库不存在时抛 ApiError(code=1003)。"""
    path = db_path()
    if not path.exists():
        raise ApiError(
            CODE_DB_UNAVAILABLE,
            f"数据库未就绪：{path} 不存在，请先运行 pipeline/06_build_db.py",
            503,
            data={"dbPath": str(path)},
        )
    try:
        uri = f"{path.as_uri()}?mode=ro"
    except ValueError:  # 极端路径无法转 URI 时退化为普通 file: 形式
        uri = f"file:{path.as_posix()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=15.0)
    except sqlite3.Error as exc:  # pragma: no cover - 只有损坏/权限问题才触发
        raise ApiError(CODE_DB_UNAVAILABLE, f"数据库连接失败：{exc}", 503) from exc
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only=ON")
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------- 结果缓存
_CACHE: dict[tuple[Any, ...], tuple[float, Any]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 256


def _cache_ttl() -> float:
    try:
        return float(os.environ.get(CACHE_ENV, "30"))
    except ValueError:
        return 30.0


def cached(name: str, params: Sequence[Any], builder: Callable[[], Any]) -> Any:
    """按 (库路径, 库 mtime, 名称, 参数) 做短 TTL 缓存。

    2.1M 行明细表上的全表聚合单次约 1s，前端一次页面会并发调用多个接口，
    因此对聚合结果做 30s 缓存（环境变量 API_CACHE_TTL=0 可关闭）。
    """
    ttl = _cache_ttl()
    if ttl <= 0:
        return builder()
    path = db_path()
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        mtime = 0
    key = (str(path), mtime, name, tuple(params))
    now = time.monotonic()
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit and now - hit[0] < ttl:
            return copy.deepcopy(hit[1])
    value = builder()
    with _CACHE_LOCK:
        if len(_CACHE) >= _CACHE_MAX:
            _CACHE.clear()
        _CACHE[key] = (now, copy.deepcopy(value))
    return value


# ---------------------------------------------------------------- 结构自省
_SCHEMA_CACHE: dict[tuple[str, int], dict[str, list[str]]] = {}


def schema() -> dict[str, list[str]]:
    """返回 {表名: [列名, ...]}；库不存在或读取失败时返回空字典。"""
    path = db_path()
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        mtime = 0
    key = (str(path), mtime)
    hit = _SCHEMA_CACHE.get(key)
    if hit is not None:
        return hit
    result: dict[str, list[str]] = {}
    if path.exists():
        try:
            with connection() as conn:
                tables = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
                ).fetchall()
                for row in tables:
                    name = str(row["name"])
                    safe = name.replace('"', '""')
                    cols = conn.execute(f'PRAGMA table_info("{safe}")').fetchall()
                    result[name] = [str(c["name"]) for c in cols]
        except (sqlite3.Error, ApiError):
            result = {}
    _SCHEMA_CACHE.clear()
    _SCHEMA_CACHE[key] = result
    return result


def fact_columns() -> list[str]:
    """fact_brfss 的实际列名（库未构建时为空列表）。"""
    return schema().get(FACT_TABLE, [])


def _require_db() -> list[str]:
    """确认库文件与 fact_brfss 表可用，否则抛 ApiError(code=1003)。

    与"库存在但没有数据"区分开：后者返回空结果（code=0），
    前者说明数据管道还没跑完，必须显式报错，不能让前端读到假零值。
    """
    path = db_path()
    if not path.exists():
        raise ApiError(
            CODE_DB_UNAVAILABLE,
            f"数据库未就绪：{path} 不存在，请先运行 pipeline/06_build_db.py",
            503,
            data={"dbPath": str(path)},
        )
    columns = fact_columns()
    if not columns:
        raise ApiError(
            CODE_DB_UNAVAILABLE,
            f"数据库未就绪：缺少表 {FACT_TABLE}",
            503,
            data={"dbPath": str(path), "tables": sorted(schema())},
        )
    return columns


# ---------------------------------------------------------------- 数值工具
def _int(value: Any) -> int:
    return int(value) if value is not None else 0


def _ratio(numerator: Any, denominator: Any, digits: int = 6) -> float | None:
    if numerator is None or not denominator:
        return None
    return round(float(numerator) / float(denominator), digits)


def _where(clauses: Sequence[str]) -> str:
    return " WHERE " + " AND ".join(clauses) if clauses else ""


# ---------------------------------------------------------------- 指标白名单
@dataclass(frozen=True)
class MetricDef:
    """指标定义：分子/分母都是 SQL 聚合表达式，值 = 分子/分母。"""

    key: str
    label: str
    unit: str
    numerator: str
    denominator: str | None
    requires: tuple[str, ...]


def _disease_metric(field: str, key: str, label: str) -> MetricDef:
    return MetricDef(
        key=key,
        label=f"{label}患病率",
        unit="ratio",
        numerator=f"SUM(CASE WHEN {field} = 1 THEN 1 ELSE 0 END)",
        denominator=f"COUNT({field})",
        requires=(field,),
    )


TREND_METRICS: dict[str, MetricDef] = {
    "total_samples": MetricDef("total_samples", "样本量", "count", "COUNT(*)", None, ()),
    "multimorbidity_rate": MetricDef(
        "multimorbidity_rate",
        "共病率",
        "ratio",
        "SUM(CASE WHEN multimorbidity = 1 THEN 1 ELSE 0 END)",
        "COUNT(multimorbidity)",
        ("multimorbidity",),
    ),
    "chronic_avg": MetricDef(
        "chronic_avg",
        "人均慢病数",
        "count",
        "SUM(chronic_count)",
        "COUNT(chronic_count)",
        ("chronic_count",),
    ),
    "obese_rate": MetricDef(
        "obese_rate",
        "肥胖率(BMI≥30)",
        "ratio",
        "SUM(CASE WHEN bmi >= 30 THEN 1 ELSE 0 END)",
        "COUNT(bmi)",
        ("bmi",),
    ),
    "smoker_rate": MetricDef(
        "smoker_rate",
        "现吸烟率",
        "ratio",
        "SUM(CASE WHEN smoker3 IN (1, 2) THEN 1 ELSE 0 END)",
        "COUNT(smoker3)",
        ("smoker3",),
    ),
    "inactivity_rate": MetricDef(
        "inactivity_rate",
        "缺乏运动率",
        "ratio",
        # 统一 0/1 约定：phys_activity 1=有休闲运动、0=无；"缺乏运动"暴露取 0
        "SUM(CASE WHEN phys_activity = 0 THEN 1 ELSE 0 END)",
        "COUNT(phys_activity)",
        ("phys_activity",),
    ),
    "heavy_drink_rate": MetricDef(
        "heavy_drink_rate",
        "重度饮酒率",
        "ratio",
        # 统一 0/1 约定：heavy_drink 1=酗酒（由 _RFBING6 的 2 归一化而来）
        "SUM(CASE WHEN heavy_drink = 1 THEN 1 ELSE 0 END)",
        "COUNT(heavy_drink)",
        ("heavy_drink",),
    ),
}
for _field, _key, _label in DISEASES:
    TREND_METRICS[f"{_key}_rate"] = _disease_metric(_field, f"{_key}_rate", _label)


#: 可干预危险因素（9 项，key 与库内 agg_risk_factor.risk_factor 一一对应，
#: 顺序也与其 ORDER BY risk_factor 一致；SQL 表达式用于 agg 表缺失时从 fact_brfss 直算）
RISK_FACTORS: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "checkup_over_1y",
        "一年以上未做常规体检（含从未体检）",
        # CHECKUP1：1=一年内 / 2=两年内 / 3=五年内 / 4=五年以上 / 8=从未 → >1 即"一年以上未体检"
        "SUM(CASE WHEN checkup > 1 THEN 1 ELSE 0 END)",
        "COUNT(checkup)",
        "checkup",
    ),
    (
        "cost_barrier",
        "因费用而未就医",
        "SUM(CASE WHEN medcost = 1 THEN 1 ELSE 0 END)",
        "COUNT(medcost)",
        "medcost",
    ),
    (
        "current_smoker",
        "现在吸烟（每日/部分日）",
        "SUM(CASE WHEN smoker3 IN (1, 2) THEN 1 ELSE 0 END)",
        "COUNT(smoker3)",
        "smoker3",
    ),
    (
        "diff_walk",
        "行走困难",
        "SUM(CASE WHEN diffwalk = 1 THEN 1 ELSE 0 END)",
        "COUNT(diffwalk)",
        "diffwalk",
    ),
    (
        "fair_poor_health",
        "自评健康一般或差（GENHLTH≥4）",
        "SUM(CASE WHEN genhlth >= 4 THEN 1 ELSE 0 END)",
        "COUNT(genhlth)",
        "genhlth",
    ),
    (
        "heavy_drink",
        "重度饮酒",
        # 统一 0/1 约定（1=状态成立）：heavy_drink 1 表示酗酒
        "SUM(CASE WHEN heavy_drink = 1 THEN 1 ELSE 0 END)",
        "COUNT(heavy_drink)",
        "heavy_drink",
    ),
    (
        "no_personal_doctor",
        "无固定就诊医生（PERSDOC3=3）",
        "SUM(CASE WHEN persdoc = 3 THEN 1 ELSE 0 END)",
        "COUNT(persdoc)",
        "persdoc",
    ),
    (
        "no_phys_activity",
        "过去30天无体育锻炼",
        # 统一 0/1 约定：phys_activity 1=有运动、0=无，暴露取 0
        "SUM(CASE WHEN phys_activity = 0 THEN 1 ELSE 0 END)",
        "COUNT(phys_activity)",
        "phys_activity",
    ),
    (
        "obese",
        "肥胖（BMI≥30）",
        "SUM(CASE WHEN bmi >= 30 THEN 1 ELSE 0 END)",
        "COUNT(bmi)",
        "bmi",
    ),
)


# ---------------------------------------------------------------- 健康检查
def health() -> dict[str, Any]:
    """数据库与模型的自检快照；不抛异常，故障以 status=degraded 表达。"""
    path = db_path()
    model = model_path()
    data: dict[str, Any] = {
        "status": "ok",
        "dbPath": str(path),
        "dbExists": path.exists(),
        "dbUpdatedAt": None,
        "factTable": FACT_TABLE,
        "factRows": 0,
        "tables": [],
        "modelPath": str(model),
        "modelReady": model.exists(),
        "serviceTime": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    if not path.exists():
        data["status"] = "degraded"
        data["detail"] = "数据库文件不存在，请先运行 pipeline/06_build_db.py"
        return data
    data["dbUpdatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(path.stat().st_mtime))
    try:
        with connection() as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view') ORDER BY name"
            ).fetchall()
            data["tables"] = [str(r["name"]) for r in tables]
            if FACT_TABLE in data["tables"]:
                data["factRows"] = _int(
                    conn.execute(f"SELECT COUNT(*) AS n FROM {FACT_TABLE}").fetchone()["n"]
                )
            else:
                data["status"] = "degraded"
                data["detail"] = f"表 {FACT_TABLE} 不存在，数据库可能尚未构建完成"
            if MODEL_TABLE in data["tables"]:
                data["modelMetricRows"] = _int(
                    conn.execute(f"SELECT COUNT(*) AS n FROM {MODEL_TABLE}").fetchone()["n"]
                )
    except (sqlite3.Error, ApiError) as exc:
        data["status"] = "degraded"
        data["detail"] = f"数据库读取失败：{exc}"
    return data


# ---------------------------------------------------------------- 总览 KPI
def overview() -> dict[str, Any]:
    """总览 KPI：总样本、年份跨度、慢病种类、共病率、人均慢病数等。"""

    def build() -> dict[str, Any]:
        empty = {
            "totalSamples": 0,
            "yearSpan": {"min": None, "max": None, "years": 0},
            "years": [],
            "stateCount": 0,
            "chronicTypes": len(DISEASES),
            "multimorbidityCases": 0,
            "multimorbidityValid": 0,
            "multimorbidityRate": None,
            "avgChronicCount": None,
            "diabetesPrevalence": None,
        }
        columns = _require_db()
        parts = ["COUNT(*) AS total_samples"]
        if "year" in columns:
            parts += [
                "MIN(year) AS year_min",
                "MAX(year) AS year_max",
                "COUNT(DISTINCT year) AS year_count",
            ]
        if "state_fips" in columns:
            parts.append("COUNT(DISTINCT state_fips) AS state_count")
        if "multimorbidity" in columns:
            parts += [
                "SUM(CASE WHEN multimorbidity = 1 THEN 1 ELSE 0 END) AS mm_cases",
                "COUNT(multimorbidity) AS mm_valid",
            ]
        if "chronic_count" in columns:
            parts += ["SUM(chronic_count) AS cc_sum", "COUNT(chronic_count) AS cc_n"]
        if "has_diabetes" in columns:
            parts += [
                "SUM(CASE WHEN has_diabetes = 1 THEN 1 ELSE 0 END) AS dm_cases",
                "COUNT(has_diabetes) AS dm_valid",
            ]
        with connection() as conn:
            row = conn.execute(f"SELECT {', '.join(parts)} FROM {FACT_TABLE}").fetchone()
            years: list[dict[str, Any]] = []
            if "year" in columns:
                years = [
                    {"year": _int(r["year"]), "samples": _int(r["n"])}
                    for r in conn.execute(
                        f"SELECT year, COUNT(*) AS n FROM {FACT_TABLE} "
                        "WHERE year IS NOT NULL GROUP BY year ORDER BY year"
                    ).fetchall()
                ]
        keys = set(row.keys())
        total = _int(row["total_samples"])
        if total == 0:
            return empty
        data = dict(empty)
        data.update(
            {
                "totalSamples": total,
                "yearSpan": {
                    "min": row["year_min"] if "year_min" in keys else None,
                    "max": row["year_max"] if "year_max" in keys else None,
                    "years": _int(row["year_count"]) if "year_count" in keys else 0,
                },
                "years": years,
                "stateCount": _int(row["state_count"]) if "state_count" in keys else 0,
                "chronicTypes": len(DISEASES),
                "multimorbidityCases": _int(row["mm_cases"]) if "mm_cases" in keys else 0,
                "multimorbidityValid": _int(row["mm_valid"]) if "mm_valid" in keys else 0,
                "multimorbidityRate": _ratio(
                    row["mm_cases"] if "mm_cases" in keys else None,
                    row["mm_valid"] if "mm_valid" in keys else None,
                ),
                "avgChronicCount": _ratio(
                    row["cc_sum"] if "cc_sum" in keys else None,
                    row["cc_n"] if "cc_n" in keys else None,
                    3,
                ),
                "diabetesPrevalence": _ratio(
                    row["dm_cases"] if "dm_cases" in keys else None,
                    row["dm_valid"] if "dm_valid" in keys else None,
                ),
            }
        )
        return data

    return cached("overview", (), build)


# ---------------------------------------------------------------- 患病率
def prevalence(year: int | None = None, state: int | None = None) -> dict[str, Any]:
    """八种慢性病的患病率（分母为该病非空样本数）。"""

    def build() -> dict[str, Any]:
        filters = {"year": year, "state": state}
        columns = _require_db()
        diseases = [(f, k, label) for f, k, label in DISEASES if f in columns]
        clauses: list[str] = []
        params: list[Any] = []
        if year is not None and "year" in columns:
            clauses.append("year = ?")
            params.append(year)
        if state is not None and "state_fips" in columns:
            clauses.append("state_fips = ?")
            params.append(state)
        select = ["COUNT(*) AS total_samples"]
        for field, key, _label in diseases:
            select.append(f"SUM(CASE WHEN {field} = 1 THEN 1 ELSE 0 END) AS n_{key}")
            select.append(f"COUNT({field}) AS d_{key}")
        sql = f"SELECT {', '.join(select)} FROM {FACT_TABLE}" + _where(clauses)
        with connection() as conn:
            row = conn.execute(sql, params).fetchone()
        total = _int(row["total_samples"])
        if total == 0:
            return {"filters": filters, "totalSamples": 0, "items": []}
        items = []
        for field, key, label in diseases:
            cases = _int(row[f"n_{key}"])
            valid = _int(row[f"d_{key}"])
            items.append(
                {
                    "key": key,
                    "field": field,
                    "name": label,
                    "cases": cases,
                    "validSamples": valid,
                    "prevalence": _ratio(cases, valid),
                }
            )
        return {"filters": filters, "totalSamples": total, "items": items}

    return cached("prevalence", (year, state), build)


# ---------------------------------------------------------------- 年度趋势
def trend(metric: str = "multimorbidity_rate") -> dict[str, Any]:
    """指定指标的年度趋势序列。"""
    metric_def = TREND_METRICS.get(metric)
    if metric_def is None:
        raise ApiError(
            CODE_INVALID_PARAM,
            f"不支持的 metric：{metric}；可选值：{', '.join(sorted(TREND_METRICS))}",
            400,
            data={"allowed": sorted(TREND_METRICS)},
        )

    def build() -> dict[str, Any]:
        payload: dict[str, Any] = {
            "metric": metric_def.key,
            "label": metric_def.label,
            "unit": metric_def.unit,
            "series": [],
        }
        columns = _require_db()
        if "year" not in columns:
            payload["note"] = "库中缺少 year 字段，无法计算年度趋势"
            return payload
        if any(c not in columns for c in metric_def.requires):
            payload["note"] = f"库中缺少字段 {list(metric_def.requires)}，无法计算该指标"
            return payload
        select = [f"{metric_def.numerator} AS numerator"]
        select.append(f"{metric_def.denominator} AS denominator" if metric_def.denominator else "NULL AS denominator")
        sql = (
            f"SELECT year AS year, {', '.join(select)} FROM {FACT_TABLE} "
            "WHERE year IS NOT NULL GROUP BY year ORDER BY year"
        )
        with connection() as conn:
            rows = conn.execute(sql).fetchall()
        series = []
        for row in rows:
            numerator = row["numerator"]
            denominator = row["denominator"]
            value = _ratio(numerator, denominator) if denominator is not None else _int(numerator)
            series.append(
                {
                    "year": _int(row["year"]),
                    "value": value,
                    "numerator": _int(numerator),
                    "denominator": _int(denominator) if denominator is not None else None,
                }
            )
        payload["series"] = series
        return payload

    return cached("trend", (metric,), build)


# ---------------------------------------------------------------- 危险因素
RISK_FACTOR_AGG_TABLE = "agg_risk_factor"


def _total_samples(year: int | None, columns: Sequence[str]) -> int:
    """命中明细表行数（仅用于回报当前过滤条件下的样本量）。"""
    clauses: list[str] = []
    params: list[Any] = []
    if year is not None and "year" in columns:
        clauses.append("year = ?")
        params.append(year)
    with connection() as conn:
        row = conn.execute(f"SELECT COUNT(*) AS n FROM {FACT_TABLE}" + _where(clauses), params).fetchone()
    return _int(row["n"])


def _risk_factors_from_agg(year: int | None) -> list[dict[str, Any]] | None:
    """优先读物化表 agg_risk_factor：9 项口径与建库脚本完全一致，且无需全表扫描。

    不筛年份时按 分子之和/分母之和 合并（比率不能直接取平均）。
    """
    agg_columns = schema().get(RISK_FACTOR_AGG_TABLE, [])
    required = {"risk_factor", "n_positive", "n_valid"}
    if not required.issubset(set(agg_columns)):
        return None
    clauses: list[str] = []
    params: list[Any] = []
    if year is not None and "year" in agg_columns:
        clauses.append("year = ?")
        params.append(year)
    label_expr = "MAX(risk_label_cn)" if "risk_label_cn" in agg_columns else "NULL"
    sql = (
        f"SELECT risk_factor AS risk_factor, SUM(n_positive) AS n_pos, "
        f"SUM(n_valid) AS n_valid, {label_expr} AS label "
        f"FROM {RISK_FACTOR_AGG_TABLE}{_where(clauses)} GROUP BY risk_factor ORDER BY risk_factor"
    )
    with connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    if not rows:
        return None
    known = {key: (name, field) for key, name, _n, _d, field in RISK_FACTORS}
    items = []
    for row in rows:
        key = str(row["risk_factor"])
        name, field = known.get(key, (str(row["label"] or key), None))
        exposed = _int(row["n_pos"])
        valid = _int(row["n_valid"])
        items.append(
            {
                "key": key,
                "name": name,
                "field": field,
                "exposed": exposed,
                "validSamples": valid,
                "rate": _ratio(exposed, valid),
            }
        )
    return items


def _risk_factors_from_fact(year: int | None, columns: Sequence[str]) -> list[dict[str, Any]] | None:
    """agg 表缺失时的兜底：从 fact_brfss 一次性扫描算出同样 9 项。"""
    available = [f for f in RISK_FACTORS if f[4] in columns]
    if not available:
        return None
    clauses: list[str] = []
    params: list[Any] = []
    if year is not None and "year" in columns:
        clauses.append("year = ?")
        params.append(year)
    select = ["COUNT(*) AS total_samples"]
    for key, _name, numerator_sql, denominator_sql, _field in available:
        select.append(f"{numerator_sql} AS n_{key}")
        select.append(f"{denominator_sql} AS d_{key}")
    sql = f"SELECT {', '.join(select)} FROM {FACT_TABLE}" + _where(clauses)
    with connection() as conn:
        row = conn.execute(sql, params).fetchone()
    if _int(row["total_samples"]) == 0:
        return None
    items = []
    for key, name, _numerator_sql, _denominator_sql, field in available:
        exposed = _int(row[f"n_{key}"])
        valid = _int(row[f"d_{key}"])
        items.append(
            {
                "key": key,
                "name": name,
                "field": field,
                "exposed": exposed,
                "validSamples": valid,
                "rate": _ratio(exposed, valid),
            }
        )
    return items


def risk_factors(year: int | None = None) -> dict[str, Any]:
    """9 项可干预危险因素暴露率。

    数据来源优先级：物化表 agg_risk_factor（与建库脚本同口径，9 项一一对应）
    → 缺表/空表时从 fact_brfss 直算（谓词与 agg 表完全一致）。
    """

    def build() -> dict[str, Any]:
        filters = {"year": year}
        columns = _require_db()
        items = _risk_factors_from_agg(year)
        source = "table:agg_risk_factor"
        if items is None:
            items = _risk_factors_from_fact(year, columns)
            source = "fact_brfss"
        if items is None:
            return {"filters": filters, "source": source, "totalSamples": 0, "items": []}
        return {
            "filters": filters,
            "source": source,
            "totalSamples": _total_samples(year, columns),
            "items": items,
        }

    return cached("risk_factors", (year,), build)


# ---------------------------------------------------------------- 风险分层
STRATUM_AGG_TABLE = "agg_risk_stratum"


def _stratify_from_agg() -> dict[str, Any] | None:
    """优先用物化表 agg_risk_stratum（chronic_count / age_grp 两个维度），避免全表扫描。"""
    agg_columns = set(schema().get(STRATUM_AGG_TABLE, []))
    if not {"dimension", "stratum_code", "n", "n_multimorbidity"}.issubset(agg_columns):
        return None
    sql = (
        f"SELECT dimension AS dimension, stratum_code AS stratum_code, n AS n, "
        f"n_multimorbidity AS mm FROM {STRATUM_AGG_TABLE} "
        "WHERE dimension IN ('chronic_count', 'age_grp') ORDER BY dimension, stratum_code"
    )
    with connection() as conn:
        rows = conn.execute(sql).fetchall()
    chronic = [r for r in rows if r["dimension"] == "chronic_count"]
    ages = [r for r in rows if r["dimension"] == "age_grp"]
    if not chronic:
        return None
    valid = sum(_int(r["n"]) for r in chronic)
    multimorbidity = sum(_int(r["mm"]) for r in chronic)
    buckets = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}
    for row in chronic:
        count = _int(row["stratum_code"])
        index = count if count <= 3 else 4
        buckets[index] += _int(row["n"])
    labels = {0: "0 种", 1: "1 种", 2: "2 种", 3: "3 种", 4: "≥4 种"}
    low = buckets[0] + buckets[1]
    mid = buckets[2] + buckets[3]
    high = buckets[4]
    return {
        "totalSamples": 0,  # 由调用方补真实明细行数
        "validSamples": valid,
        "source": f"table:{STRATUM_AGG_TABLE}",
        "distribution": [
            {
                "chronicCount": index,
                "label": labels[index],
                "samples": buckets[index],
                "share": _ratio(buckets[index], valid),
            }
            for index in (0, 1, 2, 3, 4)
        ],
        "levels": [
            {"level": "低风险", "rule": "慢病数 0-1 种", "samples": low, "share": _ratio(low, valid)},
            {"level": "中风险", "rule": "慢病数 2-3 种", "samples": mid, "share": _ratio(mid, valid)},
            {"level": "高风险", "rule": "慢病数 ≥4 种", "samples": high, "share": _ratio(high, valid)},
        ],
        "multimorbidityRate": _ratio(multimorbidity, valid),
        "byAge": [
            {
                "ageGrp": _int(r["stratum_code"]),
                "ageLabel": AGE_GROUP_LABELS.get(_int(r["stratum_code"]), str(_int(r["stratum_code"]))),
                "samples": _int(r["n"]),
                "multimorbidityCases": _int(r["mm"]),
                "multimorbidityRate": _ratio(r["mm"], r["n"]),
            }
            for r in ages
        ],
    }


def _stratify_from_fact(columns: Sequence[str]) -> dict[str, Any]:
    """兜底路径：从 fact_brfss 聚合（agg 表缺失时使用，需两次全表扫描）。"""
    payload: dict[str, Any] = {
        "totalSamples": 0,
        "validSamples": 0,
        "source": "fact_brfss",
        "distribution": [],
        "levels": [],
        "byAge": [],
    }
    if "chronic_count" not in columns:
        payload["note"] = "库中缺少 chronic_count 字段，无法分层"
        return payload
    sql = f"""
        SELECT
            SUM(CASE WHEN chronic_count = 0 THEN 1 ELSE 0 END) AS c0,
            SUM(CASE WHEN chronic_count = 1 THEN 1 ELSE 0 END) AS c1,
            SUM(CASE WHEN chronic_count = 2 THEN 1 ELSE 0 END) AS c2,
            SUM(CASE WHEN chronic_count = 3 THEN 1 ELSE 0 END) AS c3,
            SUM(CASE WHEN chronic_count >= 4 THEN 1 ELSE 0 END) AS c4,
            COUNT(*) AS total,
            COUNT(chronic_count) AS valid
        FROM {FACT_TABLE}
    """
    by_age_sql = None
    if "age_grp" in columns and "multimorbidity" in columns:
        by_age_sql = f"""
            SELECT age_grp AS age_grp,
                   COUNT(*) AS samples,
                   SUM(CASE WHEN multimorbidity = 1 THEN 1 ELSE 0 END) AS mm_cases,
                   COUNT(multimorbidity) AS mm_valid
            FROM {FACT_TABLE}
            WHERE age_grp IS NOT NULL
            GROUP BY age_grp
            ORDER BY age_grp
        """
    with connection() as conn:
        row = conn.execute(sql).fetchone()
        age_rows = conn.execute(by_age_sql).fetchall() if by_age_sql else []
    total = _int(row["total"])
    valid = _int(row["valid"])
    if total == 0:
        return payload
    buckets = [
        (0, "0 种", row["c0"]),
        (1, "1 种", row["c1"]),
        (2, "2 种", row["c2"]),
        (3, "3 种", row["c3"]),
        (4, "≥4 种", row["c4"]),
    ]
    payload["totalSamples"] = total
    payload["validSamples"] = valid
    payload["distribution"] = [
        {
            "chronicCount": count,
            "label": label,
            "samples": _int(samples),
            "share": _ratio(samples, valid),
        }
        for count, label, samples in buckets
    ]
    low = _int(row["c0"]) + _int(row["c1"])
    mid = _int(row["c2"]) + _int(row["c3"])
    high = _int(row["c4"])
    payload["levels"] = [
        {"level": "低风险", "rule": "慢病数 0-1 种", "samples": low, "share": _ratio(low, valid)},
        {"level": "中风险", "rule": "慢病数 2-3 种", "samples": mid, "share": _ratio(mid, valid)},
        {"level": "高风险", "rule": "慢病数 ≥4 种", "samples": high, "share": _ratio(high, valid)},
    ]
    payload["multimorbidityRate"] = _ratio(mid + high, valid)
    payload["byAge"] = [
        {
            "ageGrp": _int(r["age_grp"]),
            "ageLabel": AGE_GROUP_LABELS.get(_int(r["age_grp"]), str(_int(r["age_grp"]))),
            "samples": _int(r["samples"]),
            "multimorbidityCases": _int(r["mm_cases"]),
            "multimorbidityRate": _ratio(r["mm_cases"], r["mm_valid"]),
        }
        for r in age_rows
    ]
    return payload


def stratify() -> dict[str, Any]:
    """共病数量分布、风险等级分布与年龄组共病率。

    数据来源优先级：物化表 agg_risk_stratum（32 行，毫秒级）→ fact_brfss 直算（兜底）。
    """

    def build() -> dict[str, Any]:
        columns = _require_db()
        payload = _stratify_from_agg()
        if payload is not None:
            payload["totalSamples"] = _total_samples(None, columns)
            return payload
        return _stratify_from_fact(columns)

    return cached("stratify", (), build)


# ---------------------------------------------------------------- 州级指标
def _state_names() -> dict[int, str]:
    """优先取 dim_state 的名称，缺失时用参考字典。"""
    names: dict[int, str] = {}
    dims = [t for t in schema() if t.startswith("dim") and "state" in t]
    for table in dims:
        cols = schema().get(table, [])
        fips_col = next((c for c in cols if c in ("state_fips", "fips", "state_code")), None)
        name_col = next(
            (c for c in cols if c in ("state_name", "name", "state", "state_label")), None
        )
        if not fips_col or not name_col:
            continue
        try:
            with connection() as conn:
                for row in conn.execute(f'SELECT "{fips_col}" AS f, "{name_col}" AS n FROM "{table}"'):
                    if row["f"] is not None and row["n"] is not None:
                        names[_int(row["f"])] = str(row["n"])
        except sqlite3.Error:  # pragma: no cover - 只读损坏场景
            continue
        if names:
            break
    # 库内 dim 表可能只覆盖部分州，缺的用参考字典补齐，避免地图出现裸数字
    merged = dict(STATE_FIPS_NAMES)
    merged.update(names)
    return merged


def geo_states(metric: str = "multimorbidity_rate") -> dict[str, Any]:
    """州级指标（供前端 ECharts 地图使用）。"""
    metric_def = TREND_METRICS.get(metric)
    if metric_def is None:
        raise ApiError(
            CODE_INVALID_PARAM,
            f"不支持的 metric：{metric}；可选值：{', '.join(sorted(TREND_METRICS))}",
            400,
            data={"allowed": sorted(TREND_METRICS)},
        )

    def build() -> dict[str, Any]:
        payload: dict[str, Any] = {
            "metric": metric_def.key,
            "label": metric_def.label,
            "unit": metric_def.unit,
            "items": [],
        }
        columns = _require_db()
        if "state_fips" not in columns:
            payload["note"] = "库中缺少 state_fips 字段，无法计算州级指标"
            return payload
        if any(c not in columns for c in metric_def.requires):
            payload["note"] = f"库中缺少字段 {list(metric_def.requires)}，无法计算该指标"
            return payload
        denominator = metric_def.denominator or "NULL"
        sql = (
            f"SELECT state_fips AS state_fips, {metric_def.numerator} AS numerator, "
            f"{denominator} AS denominator FROM {FACT_TABLE} "
            "WHERE state_fips IS NOT NULL GROUP BY state_fips ORDER BY state_fips"
        )
        with connection() as conn:
            rows = conn.execute(sql).fetchall()
        names = _state_names()
        items = []
        for row in rows:
            fips = _int(row["state_fips"])
            numerator = row["numerator"]
            denominator_value = row["denominator"]
            value = _ratio(numerator, denominator_value) if denominator_value is not None else _int(numerator)
            items.append(
                {
                    "stateFips": fips,
                    "stateName": names.get(fips, str(fips)),
                    "value": value,
                    "numerator": _int(numerator),
                    "denominator": _int(denominator_value) if denominator_value is not None else None,
                }
            )
        payload["items"] = items
        return payload

    return cached("geo_states", (metric,), build)


# ---------------------------------------------------------------- 模型指标
def model_metrics() -> dict[str, Any]:
    """模型评估指标：优先读库表 model_metrics，退化读 artifacts/metrics/*.json。"""

    def build() -> dict[str, Any]:
        payload: dict[str, Any] = {"source": "none", "count": 0, "items": []}
        _require_db()
        tables = schema()
        if MODEL_TABLE in tables:
            try:
                with connection() as conn:
                    rows = conn.execute(f"SELECT * FROM {MODEL_TABLE}").fetchall()
                if rows:
                    payload["source"] = f"table:{MODEL_TABLE}"
                    payload["items"] = [dict(r) for r in rows]
                    payload["count"] = len(rows)
                    return payload
            except sqlite3.Error:  # pragma: no cover - 只读损坏场景
                pass
        if METRICS_DIR.is_dir():
            items: list[dict[str, Any]] = []
            for file in sorted(METRICS_DIR.glob("*.json")):
                try:
                    content = json.loads(file.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if isinstance(content, list):
                    rows = [r for r in content if isinstance(r, dict)]
                elif isinstance(content, dict):
                    # 只接受显式声明为指标集合的结构；pipeline_log 之类的日志文件跳过，
                    # 避免把流水线日志误当成模型指标返回。
                    rows = []
                    for field in ("metrics", "models", "items"):
                        value = content.get(field)
                        if isinstance(value, list):
                            rows = [r for r in value if isinstance(r, dict)]
                            break
                else:
                    rows = []
                for row in rows:
                    if isinstance(row, dict):
                        item = dict(row)
                        item.setdefault("sourceFile", file.name)
                        items.append(item)
            if items:
                payload["source"] = "artifacts/metrics"
                payload["items"] = items
                payload["count"] = len(items)
        return payload

    return cached("model_metrics", (), build)
