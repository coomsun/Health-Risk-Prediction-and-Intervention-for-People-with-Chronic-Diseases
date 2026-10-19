"""FastAPI 应用：按冻结契约实现 9 个 RESTful 接口。

接口清单（_设计规格.md 第 5 节）
--------------------------------
GET  /api/v1/health              健康检查（DB 连接 + 行数）
GET  /api/v1/overview            总览 KPI
GET  /api/v1/chronic/prevalence  各慢病患病率（可按 year / state 过滤）
GET  /api/v1/trend               指标年度趋势（metric 选择）
GET  /api/v1/risk/factors        危险因素暴露率（可按 year 过滤）
GET  /api/v1/risk/stratify       风险分层分布
GET  /api/v1/geo/states          州级指标（地图）
GET  /api/v1/model/metrics       模型指标与对比
POST /api/v1/predict             在线个体风险预测

启动：python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from . import __version__, auth, contract, queries
from .contract import (
    CODE_INVALID_PARAM,
    CODE_MODEL_NOT_READY,
    CODE_PREDICT_FAILED,
    ApiError,
    ok,
)

LOGGER = logging.getLogger("chronic.api")

APP_TITLE = "慢性病患者健康风险预测与干预 API"
APP_DESCRIPTION = (
    "基于 CDC BRFSS 2019-2023 五年合并数据（约 213 万条）的慢性病风险分析服务。"
    "所有统计数字均来自 SQLite（db/chronic_risk.db）的真实聚合查询，"
    "统一响应信封为 {code, message, data, traceId, timestamp}。"
)

#: 参数合法域（仅为入参防呆；实际数据年份/州由库内数据决定）
YEAR_MIN, YEAR_MAX = 2000, 2030
STATE_MIN, STATE_MAX = 1, 99

#: 在线预测风险等级阈值（决策规则，非统计量；写入口径文档）
RISK_THRESHOLDS: dict[str, float] = {"low": 0.10, "high": 0.30}

STARTED_AT = time.monotonic()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    LOGGER.warning("服务启动 | 版本=%s | DB=%s | 模型=%s", __version__, queries.db_path(), queries.model_path())
    yield
    LOGGER.warning("服务关闭")


app = FastAPI(
    title=APP_TITLE,
    version=__version__,
    description=APP_DESCRIPTION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# 统一信封 / 异常处理 / X-Response-Time 中间件
contract.install(app)

# 前端页面可能以 file:// 或 http://127.0.0.1:5500 等方式打开，放开跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Response-Time", "X-Trace-Id"],
)


# ---------------------------------------------------------------- 入参模型
class LoginRequest(BaseModel):
    """登录入参。演示账号见部署文档（默认 demo/demo12345）。"""

    username: str = Field(..., min_length=1, max_length=64, description="用户名")
    password: str = Field(..., min_length=1, max_length=128, description="密码")
    ttl: int | None = Field(None, ge=60, le=86400, description="令牌有效期（秒），默认 3600")


class PredictRequest(BaseModel):
    """在线个体风险预测入参。

    字段名与 fact_brfss 列名一致，全部可选；缺省特征置为 NaN 交给模型处理
    （LightGBM / sklearn 的树模型原生支持缺失值）。
    """

    model_config = ConfigDict(extra="ignore")

    year: int | None = Field(None, ge=YEAR_MIN, le=YEAR_MAX, description="调查年份")
    state_fips: int | None = Field(None, ge=STATE_MIN, le=STATE_MAX, description="州 FIPS 编码")
    month: int | None = Field(None, ge=1, le=12, description="调查月份")
    sex: int | None = Field(None, ge=1, le=2, description="_SEX 性别：1 男 / 2 女")
    age: int | None = Field(None, ge=0, le=80, description="_AGE80 年龄")
    age_grp: int | None = Field(None, ge=1, le=13, description="_AGEG5YR 年龄组：1..13")
    race: int | None = Field(None, ge=1, le=8, description="_MRACE 种族编码")
    hispanic: int | None = Field(None, ge=1, le=9, description="_HISPANC 西语裔编码")
    educa: int | None = Field(None, ge=1, le=6, description="EDUCA 教育程度")
    income_grp: int | None = Field(None, ge=1, le=8, description="_INCOMG 收入组")
    employ: int | None = Field(None, ge=1, le=9, description="EMPLOY1 就业状态")
    marital: int | None = Field(None, ge=1, le=6, description="MARITAL 婚姻状态")
    veteran: int | None = Field(None, ge=1, le=4, description="VETERAN3 退伍军人")
    bmi: float | None = Field(None, ge=10, le=70, description="BMI（_BMI5/100）")
    obese: int | None = Field(None, ge=0, le=1, description="是否肥胖（bmi≥30）")
    smoker3: int | None = Field(None, ge=1, le=4, description="_SMOKER3 吸烟状态：1 每日 / 2 部分日 / 3 曾经 / 4 从不")
    phys_activity: int | None = Field(None, ge=0, le=1, description="体育锻炼：1 有休闲运动 / 0 无")
    heavy_drink: int | None = Field(None, ge=0, le=1, description="重度饮酒：1 酗酒 / 0 否")
    genhlth: int | None = Field(None, ge=1, le=5, description="GENHLTH 自评健康：1 优 … 5 差")
    poor_health: int | None = Field(None, ge=1, le=3, description="_RFHLTH 健康不良天数分层")
    menthlth: int | None = Field(None, ge=0, le=30, description="近 30 天心理不良天数")
    physhlth: int | None = Field(None, ge=0, le=30, description="近 30 天生理不良天数")
    diffwalk: int | None = Field(None, ge=0, le=1, description="行走困难：1 是 / 0 否")
    medcost: int | None = Field(None, ge=0, le=1, description="因费用未就医：1 是 / 0 否")
    checkup: int | None = Field(None, ge=1, le=8, description="CHECKUP1 体检时间")
    persdoc: int | None = Field(None, ge=1, le=3, description="PERSDOC3 固定就诊医生")


# ---------------------------------------------------------------- 模型加载
_MODEL_CACHE: dict[tuple[str, int, int], Any] = {}
_MODEL_LOCK = threading.Lock()


def _load_model(path: Path) -> Any:
    """按 (路径, mtime, 大小) 缓存 joblib 模型，避免每次请求重复反序列化。"""
    import joblib

    stat = path.stat()
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    with _MODEL_LOCK:
        cached_model = _MODEL_CACHE.get(key)
    if cached_model is not None:
        return cached_model
    try:
        model = joblib.load(path)
    except Exception as exc:  # noqa: BLE001 - 反序列化失败一律按"模型未就绪"处理
        raise ApiError(
            CODE_MODEL_NOT_READY,
            "模型未就绪",
            503,
            data={"modelPath": str(path), "detail": f"{type(exc).__name__}: {exc}"},
        ) from exc
    with _MODEL_LOCK:
        _MODEL_CACHE.clear()
        _MODEL_CACHE[key] = model
    return model


def _feature_names(model: Any, model_dir: Path) -> list[str] | None:
    """推断模型入参列名：sidecar JSON > feature_names_in_ > LightGBM booster。"""
    for sidecar_name in ("feature_names.json", "model_meta.json", "metadata.json"):
        sidecar = model_dir / sidecar_name
        if not sidecar.exists():
            continue
        try:
            content = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            content = None
        if isinstance(content, list) and content and all(isinstance(x, str) for x in content):
            return list(content)
        if isinstance(content, dict):
            for field in ("features", "featureNames", "feature_names", "columns"):
                value = content.get(field)
                if isinstance(value, list) and value and all(isinstance(x, str) for x in value):
                    return list(value)
    candidates: list[Any] = [model]
    steps = getattr(model, "steps", None)
    if steps:
        candidates.extend(step for _name, step in steps)
    for estimator in candidates:
        names = getattr(estimator, "feature_names_in_", None)
        if names is not None and len(names):
            return [str(n) for n in list(names)]
        booster = getattr(estimator, "booster_", None)
        extractor = getattr(booster, "feature_name", None)
        if callable(extractor):
            try:
                found = [str(n) for n in extractor() if str(n)]
            except Exception:  # noqa: BLE001 - 探测失败继续尝试下一个候选
                found = []
            if found:
                return found
        get_booster = getattr(estimator, "get_booster", None)
        if callable(get_booster):
            try:
                found = [str(n) for n in get_booster().feature_name() if str(n)]
            except Exception:  # noqa: BLE001
                found = []
            if found:
                return found
    return None


def _predict_probability(model: Any, frame: Any) -> float:
    """把不同模型的输出统一成"阳性概率"。"""
    import numpy as np

    if hasattr(model, "predict_proba"):
        array = np.asarray(model.predict_proba(frame))
        if array.ndim == 2:
            return float(array[0, -1])
        return float(array.ravel()[0])
    if hasattr(model, "decision_function"):
        score = float(np.asarray(model.decision_function(frame)).ravel()[0])
        return 1.0 / (1.0 + math.exp(-score))
    prediction = np.asarray(model.predict(frame)).ravel()
    return float(prediction[0])


def _risk_level(probability: float) -> str:
    if probability >= RISK_THRESHOLDS["high"]:
        return "高风险"
    if probability >= RISK_THRESHOLDS["low"]:
        return "中风险"
    return "低风险"


# ---------------------------------------------------------------- 通用查询
@app.get("/", include_in_schema=False)
def index(request: Request) -> dict[str, Any]:
    """根路径：返回服务自述与接口清单，便于人工探活。"""
    return ok(
        request,
        {
            "service": APP_TITLE,
            "version": __version__,
            "docs": "/docs",
            "openapi": "/openapi.json",
            "endpoints": [
                "GET /api/v1/health",
                "GET /api/v1/overview",
                "GET /api/v1/chronic/prevalence",
                "GET /api/v1/trend",
                "GET /api/v1/risk/factors",
                "GET /api/v1/risk/stratify",
                "GET /api/v1/geo/states",
                "GET /api/v1/model/metrics",
                "POST /api/v1/predict",
            ],
        },
    )


@app.post("/api/v1/auth/login", summary="登录并签发 JWT 令牌", tags=["鉴权"])
def login(payload: LoginRequest, request: Request) -> dict[str, Any]:
    """校验用户名密码，成功后返回 Bearer 令牌。

    令牌用于调用受保护接口（如 POST /api/v1/predict）。
    查询类接口默认公开，无需登录即可演示。
    """
    if not auth.authenticate(payload.username, payload.password):
        raise ApiError(CODE_INVALID_PARAM, "用户名或密码错误", 401)
    token = auth.issue_token(payload.username, payload.ttl)
    return ok(request, {**token, "username": payload.username})


@app.get("/api/v1/auth/me", summary="查询当前令牌身份", tags=["鉴权"])
def whoami(request: Request, claims: dict[str, Any] = Depends(auth.require_token)) -> dict[str, Any]:
    return ok(request, {"username": claims.get("sub"), "issuedAt": claims.get("iat"), "expiresAt": claims.get("exp")})


@app.get("/api/v1/health", summary="健康检查（数据库连接与行数）")
def health(request: Request) -> dict[str, Any]:
    data = queries.health()
    data["version"] = __version__
    data["uptimeSeconds"] = round(time.monotonic() - STARTED_AT, 2)
    return ok(request, data)


@app.get("/api/v1/overview", summary="总览 KPI")
def overview(request: Request) -> dict[str, Any]:
    return ok(request, queries.overview())


@app.get("/api/v1/chronic/prevalence", summary="各慢病患病率")
def chronic_prevalence(
    request: Request,
    year: int | None = Query(None, ge=YEAR_MIN, le=YEAR_MAX, description="调查年份，如 2023"),
    state: int | None = Query(None, ge=STATE_MIN, le=STATE_MAX, description="州 FIPS 编码，如 6 表示 California"),
) -> dict[str, Any]:
    return ok(request, queries.prevalence(year=year, state=state))


@app.get("/api/v1/trend", summary="指标年度趋势")
def trend(
    request: Request,
    metric: str = Query("multimorbidity_rate", description="指标名，可选值见响应中的 allowed 列表"),
) -> dict[str, Any]:
    return ok(request, queries.trend(metric))


@app.get("/api/v1/risk/factors", summary="危险因素暴露率")
def risk_factors(
    request: Request,
    year: int | None = Query(None, ge=YEAR_MIN, le=YEAR_MAX, description="调查年份"),
) -> dict[str, Any]:
    return ok(request, queries.risk_factors(year=year))


@app.get("/api/v1/risk/stratify", summary="风险分层分布")
def risk_stratify(request: Request) -> dict[str, Any]:
    return ok(request, queries.stratify())


@app.get("/api/v1/geo/states", summary="州级指标（地图）")
def geo_states(
    request: Request,
    metric: str = Query("multimorbidity_rate", description="指标名，与 /trend 的 metric 一致"),
) -> dict[str, Any]:
    return ok(request, queries.geo_states(metric))


@app.get("/api/v1/model/metrics", summary="模型指标与对比")
def model_metrics(request: Request) -> dict[str, Any]:
    return ok(request, queries.model_metrics())


@app.post("/api/v1/predict", summary="在线个体风险预测（需 JWT 令牌）", tags=["预测"])
def predict(payload: PredictRequest, request: Request,
            claims: dict[str, Any] = Depends(auth.require_token)) -> dict[str, Any]:
    started = time.perf_counter()
    provided = {key: value for key, value in payload.model_dump().items() if value is not None}
    if not provided:
        raise ApiError(
            CODE_INVALID_PARAM,
            "参数校验失败：请至少提供一项特征（如 bmi、smoker3、age_grp）",
            400,
        )
    path = queries.model_path()
    if not path.exists():
        raise ApiError(
            CODE_MODEL_NOT_READY,
            "模型未就绪",
            503,
            data={
                "modelPath": str(path),
                "hint": "请先运行 pipeline/05_train.py 生成 artifacts/model/model.joblib",
            },
        )
    import pandas as pd  # 延迟导入：只有预测接口需要 pandas

    model = _load_model(path)
    features = _feature_names(model, path.parent)
    missing: list[str] = []
    try:
        if features:
            missing = [name for name in features if name not in provided]
            if len(missing) == len(features):
                raise ApiError(
                    CODE_PREDICT_FAILED,
                    "预测执行失败：入参与模型特征完全不匹配，未提供任何模型需要的列",
                    400,
                    data={
                        "modelFeatures": features,
                        "provided": sorted(provided),
                        "hint": "请按 modelFeatures 中的字段名提交（见 docs/接口文档.md 3.9 节）",
                    },
                )
            row = {name: provided.get(name, float("nan")) for name in features}
            frame = pd.DataFrame([row], columns=features)
        else:
            frame = pd.DataFrame([provided])
        probability = _predict_probability(model, frame)
    except ApiError:
        raise  # 业务异常原样抛出，不要被下面的兜底包装覆盖状态码
    except Exception as exc:  # noqa: BLE001 - 模型与特征不匹配等一律转业务错误
        raise ApiError(
            CODE_PREDICT_FAILED,
            f"预测执行失败：{type(exc).__name__}: {exc}",
            500,
            data={"featureNames": features, "provided": sorted(provided)},
        ) from exc
    stat = path.stat()
    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    return ok(
        request,
        {
            "probability": round(probability, 6),
            "prediction": 1 if probability >= 0.5 else 0,
            "riskLevel": _risk_level(probability),
            "thresholds": RISK_THRESHOLDS,
            "model": {
                "path": str(path),
                "fileName": path.name,
                "sizeBytes": stat.st_size,
                "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(stat.st_mtime)),
                "featureNames": features,
            },
            "missingFeatures": missing,
            "features": provided,
            "latencyMs": latency_ms,
        },
    )
