# -*- coding: utf-8 -*-
"""03_eda_spark.py —— PySpark EDA + 假设验证（报告第 3 章与 4.1 章的数据底座）

内容（全部在真实数据上运行，n=2,136,402，2019–2023 合并）：
  1. 分布特征：8 种慢病逐年患病率、chronic_count 分布、共病率按年龄/性别/收入/教育/州；
  2. 相关性：14 个二值危险因素 + BMI 的关联矩阵（Cramér's V / 点二列相关），
     通过"联合分布位掩码"一次聚合精确算出，不做抽样；
  3. 时序模式：2019→2023 各慢病率与共病率变化（含 2020/2021 COVID 年对照）；
  4. 加权对照：用 _LLCPWT 计算加权患病率，与未加权抽样比例并列（严谨性）；
  5. 假设验证方式 B：暴露分层共病率 + 卡方检验 + Cramér's V 效应量；
  6. 假设验证方式 A：多因素 Logistic 回归（statsmodels）→ 调整后 OR 与 95%CI；
  7. 剂量-反应：可干预风险因素个数 0→3 的共病率。
产出：
  artifacts/metrics/eda_metrics.json        分布/相关/时序/加权
  artifacts/metrics/hypothesis_metrics.json 假设检验全部统计量
  artifacts/figures/*.png                   12 张 300dpi 中文图

注意：本机 Spark 4.2 缺 winutils.exe，DataFrameWriter 不可用，
因此本脚本 **只读 + 只计算**，结果一律 collect 到 driver 后用 matplotlib/JSON 落盘。

用法：python pipeline/03_eda_spark.py
"""
from __future__ import annotations

import json
import math
import os
import signal
import sqlite3
import sys
import time
from datetime import datetime, timezone

os.environ.setdefault("JAVA_HOME", r"D:\jdk17")
os.environ.setdefault("SPARK_HOME", r"D:\sparkhome")
_PY = r"D:\期末作业\.venv\Scripts\python.exe"
os.environ.setdefault("PYSPARK_PYTHON", _PY)
os.environ.setdefault("PYSPARK_DRIVER_PYTHON", _PY)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pyspark.sql import SparkSession, functions as F
from scipy import stats
import statsmodels.api as sm

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(ROOT, "data", "raw")
PROCESSED = os.path.join(ROOT, "data", "processed", "brfss_clean.parquet")
DB_PATH = os.path.join(ROOT, "db", "chronic_risk.db")
FIG_DIR = os.path.join(ROOT, "artifacts", "figures")
MET_DIR = os.path.join(ROOT, "artifacts", "metrics")
EDA_JSON = os.path.join(MET_DIR, "eda_metrics.json")
HYP_JSON = os.path.join(MET_DIR, "hypothesis_metrics.json")
LOG_PATH = os.path.join(MET_DIR, "pipeline_log.json")
YEARS = [2019, 2020, 2021, 2022, 2023]

DISEASES = [
    ("has_diabetes", "糖尿病"),
    ("has_mi", "心肌梗死"),
    ("has_chd", "冠心病"),
    ("has_stroke", "卒中"),
    ("has_copd", "慢阻肺"),
    ("has_asthma", "哮喘"),
    ("has_kidney", "慢性肾病"),
    ("has_depression", "抑郁障碍"),
]
AGE_GRP_LABEL = {
    1: "18-24", 2: "25-29", 3: "30-34", 4: "35-39", 5: "40-44", 6: "45-49", 7: "50-54",
    8: "55-59", 9: "60-64", 10: "65-69", 11: "70-74", 12: "75-79", 13: "80+",
}
INCOME_LABEL = {1: "<1.5万", 2: "1.5-2.5万", 3: "2.5-3.5万", 4: "3.5-5万", 5: "≥5万"}
EDUCA_LABEL = {1: "未上学", 2: "小学", 3: "初中", 4: "高中/GED", 5: "大学1-3年", 6: "大学4年+"}
SEX_LABEL = {1: "男", 2: "女"}
STATE_FALLBACK = {
    1: "AL", 2: "AK", 4: "AZ", 5: "AR", 6: "CA", 8: "CO", 9: "CT", 10: "DE", 11: "DC",
    12: "FL", 13: "GA", 15: "HI", 16: "ID", 17: "IL", 18: "IN", 19: "IA", 20: "KS", 21: "KY",
    22: "LA", 23: "ME", 24: "MD", 25: "MA", 26: "MI", 27: "MN", 28: "MS", 29: "MO", 30: "MT",
    31: "NE", 32: "NV", 33: "NH", 34: "NJ", 35: "NM", 36: "NY", 37: "NC", 38: "ND", 39: "OH",
    40: "OK", 41: "OR", 42: "PA", 44: "RI", 45: "SC", 46: "SD", 47: "TN", 48: "TX", 49: "UT",
    50: "VT", 51: "VA", 53: "WA", 54: "WV", 55: "WI", 56: "WY", 66: "GU", 72: "PR", 78: "VI",
}

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.facecolor"] = "white"
plt.rcParams["axes.grid"] = True
plt.rcParams["grid.alpha"] = 0.25
plt.rcParams["axes.axisbelow"] = True
PALETTE = ["#2f6fb3", "#e07b39", "#4c9f70", "#b3403a", "#7b6cb3", "#8a8a8a", "#c9a227", "#3a8f9f"]


import sys as _sys
try:  # Windows 控制台默认 GBK，无法输出 ² 等字符，统一切到 UTF-8
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def log(msg: str) -> None:
    print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), msg), flush=True)


def save_fig(fig, name: str, caption: str) -> str:
    """统一落盘：300dpi + 底部口径说明。"""
    fig.text(0.008, 0.006, caption, fontsize=7.5, color="#555555", ha="left", va="bottom")
    path = os.path.join(FIG_DIR, name)
    fig.savefig(path, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    log("  图 → %s" % name)
    return path


def pct(x: float) -> float:
    return round(100.0 * float(x), 4)


# ---------------------------------------------------------------- Spark
def spark_session() -> SparkSession:
    spark = (SparkSession.builder
             .appName("brfss_eda")
             .master("local[8]")
             .config("spark.driver.memory", "4g")
             .config("spark.sql.shuffle.partitions", "8")
             .config("spark.ui.enabled", "false")
             .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")
    return spark


def load(spark: SparkSession, cols):
    """按列裁剪读取清洗后 parquet（不 cache，避免 JVM 对象膨胀）。"""
    return spark.read.parquet(PROCESSED).select(*cols)


# ---------------------------------------------------------------- 联合分布（位掩码）
BIN_VARS = [
    ("multimorbidity", "共病(慢病数≥2)"),
    ("obese", "肥胖"),
    ("smoke_current", "现吸烟"),
    ("phys_inactive", "无体力活动"),
    ("cost_barrier", "费用障碍"),
    ("no_doctor", "无固定医生"),
    ("no_checkup_1y", "超1年未体检"),
    ("diffwalk", "行走困难"),
    ("poor_health", "自评健康差"),
    ("genhlth_poor", "自评健康差/一般"),
    ("educa_low", "教育≤初中"),
    ("income_low", "收入<2.5万"),
    ("age_65plus", "年龄≥65"),
    ("sex_male", "男性"),
]
CONT_VAR = ("bmi", "BMI")

RAW_COLS_FOR_JOINT = ["multimorbidity", "obese", "smoker3", "phys_activity", "medcost",
                      "persdoc", "checkup", "diffwalk", "poor_health", "genhlth",
                      "educa", "income_grp", "age", "sex", "bmi"]


def bin_exprs():
    """14 个二值风险/协变量的 0/1 表达式（缺失保持 NULL）。"""
    e = {
        "multimorbidity": F.col("multimorbidity").cast("int"),
        "obese": F.col("obese").cast("int"),
        "smoke_current": F.when(F.col("smoker3").isin(1, 2), F.lit(1))
                          .when(F.col("smoker3").isin(3, 4), F.lit(0)).otherwise(F.lit(None).cast("int")).cast("int"),
        "phys_inactive": F.when(F.col("phys_activity").isNull(), F.lit(None).cast("int"))
                          .otherwise(1 - F.col("phys_activity")).cast("int"),
        "cost_barrier": F.col("medcost").cast("int"),
        "no_doctor": F.when(F.col("persdoc") == 3, F.lit(1))
                      .when(F.col("persdoc").isin(1, 2), F.lit(0)).otherwise(F.lit(None).cast("int")).cast("int"),
        "no_checkup_1y": F.when(F.col("checkup").isin(2, 3, 4, 8), F.lit(1))
                          .when(F.col("checkup") == 1, F.lit(0)).otherwise(F.lit(None).cast("int")).cast("int"),
        "diffwalk": F.col("diffwalk").cast("int"),
        "poor_health": F.col("poor_health").cast("int"),
        "genhlth_poor": F.when(F.col("genhlth") >= 4, F.lit(1))
                         .when(F.col("genhlth") <= 3, F.lit(0)).otherwise(F.lit(None).cast("int")).cast("int"),
        "educa_low": F.when(F.col("educa") <= 3, F.lit(1))
                      .when(F.col("educa").isNotNull(), F.lit(0)).otherwise(F.lit(None).cast("int")).cast("int"),
        "income_low": F.when(F.col("income_grp") <= 2, F.lit(1))
                       .when(F.col("income_grp").isNotNull(), F.lit(0)).otherwise(F.lit(None).cast("int")).cast("int"),
        "age_65plus": F.when(F.col("age") >= 65, F.lit(1))
                       .when(F.col("age").isNotNull(), F.lit(0)).otherwise(F.lit(None).cast("int")).cast("int"),
        "sex_male": F.when(F.col("sex") == 1, F.lit(1))
                     .when(F.col("sex") == 2, F.lit(0)).otherwise(F.lit(None).cast("int")).cast("int"),
    }
    return e


def joint_table(spark: SparkSession) -> pd.DataFrame:
    """一次 groupBy 得到 14 个二值变量的精确联合分布（位掩码 + 缺失位）。"""
    exprs = bin_exprs()
    n = len(BIN_VARS)
    code = F.lit(0)
    for i, (name, _) in enumerate(BIN_VARS):
        c = exprs[name]
        code = code + F.when(c.isNull(), F.lit(1 << (n + i))).otherwise(c * F.lit(1 << i))
    df = load(spark, RAW_COLS_FOR_JOINT)
    df = df.select(code.alias("code"), F.col("bmi").cast("double").alias("bmi"))
    agg = (df.groupBy("code")
             .agg(F.count(F.lit(1)).alias("cnt"),
                  F.count("bmi").alias("n_bmi"),
                  F.sum("bmi").alias("s_bmi"),
                  F.sum(F.col("bmi") * F.col("bmi")).alias("s_bmi2")))
    pdf = agg.toPandas()
    for c in ("n_bmi", "s_bmi", "s_bmi2"):
        pdf[c] = pdf[c].astype(float).fillna(0.0)
    log("  联合分布：%d 个取值组合，覆盖 %d 行" % (len(pdf), int(pdf["cnt"].sum())))
    return pdf


def association_matrix(pdf: pd.DataFrame) -> dict:
    """由联合分布表精确计算 Cramér's V（二值×二值）与点二列相关（BMI×二值）。"""
    n_bin = len(BIN_VARS)
    codes = pdf["code"].to_numpy(dtype=np.int64)
    cnt = pdf["cnt"].to_numpy(dtype=float)
    n_bmi = pdf["n_bmi"].to_numpy(dtype=float)
    s_bmi = pdf["s_bmi"].to_numpy(dtype=float)
    s_bmi2 = pdf["s_bmi2"].to_numpy(dtype=float)
    nrow = codes.size
    val = np.zeros((n_bin, nrow), dtype=bool)
    miss = np.zeros((n_bin, nrow), dtype=bool)
    for i in range(n_bin):
        val[i] = ((codes >> i) & 1).astype(bool)
        miss[i] = ((codes >> (n_bin + i)) & 1).astype(bool)

    names = [v for v, _ in BIN_VARS] + [CONT_VAR[0]]
    labels = [l for _, l in BIN_VARS] + [CONT_VAR[1]]
    size = len(names)
    mat = np.full((size, size), np.nan)
    detail = {}
    for i in range(n_bin):
        for j in range(i, n_bin):
            valid = (~miss[i]) & (~miss[j])
            n = cnt[valid].sum()
            if n <= 0:
                continue
            a = cnt[valid & (val[i] == 1) & (val[j] == 1)].sum()
            b = cnt[valid & (val[i] == 1) & (val[j] == 0)].sum()
            c = cnt[valid & (val[i] == 0) & (val[j] == 1)].sum()
            d = cnt[valid & (val[i] == 0) & (val[j] == 0)].sum()
            denom = math.sqrt((a + b) * (c + d) * (a + c) * (b + d)) if (a + b) * (c + d) * (a + c) * (b + d) > 0 else 0.0
            phi = (a * d - b * c) / denom if denom else 0.0
            v = abs(phi)
            mat[i, j] = mat[j, i] = v
            if i == 0:  # 共病 vs 各因素：同时给出 2x2 表与卡方检验
                chi2 = n * phi * phi
                p = float(stats.chi2.sf(chi2, 1)) if chi2 > 0 else 1.0
                detail[names[j]] = {
                    "exposure": names[j], "exposure_cn": labels[j],
                    "n": int(n), "n11": int(a), "n10": int(b), "n01": int(c), "n00": int(d),
                    "rate_exposed": round(a / (a + b), 6) if (a + b) else None,
                    "rate_unexposed": round(c / (c + d), 6) if (c + d) else None,
                    "rate_diff_pp": round(100 * (a / (a + b) - c / (c + d)), 4) if (a + b) and (c + d) else None,
                    "chi2": round(chi2, 3), "p_value": p, "cramers_v": round(v, 6),
                    "or_crude": round((a * d) / (b * c), 4) if b * c else None,
                }
    # BMI × 二值：点二列相关
    k = size - 1
    for i in range(n_bin):
        valid = (~miss[i]) & (n_bmi > 0)
        n = n_bmi[valid].sum()
        if n <= 0:
            continue
        sx = s_bmi[valid].sum()
        sxx = s_bmi2[valid].sum()
        n1 = n_bmi[valid & (val[i] == 1)].sum()
        s1 = s_bmi[valid & (val[i] == 1)].sum()
        if n1 <= 0 or n - n1 <= 0:
            continue
        mb = sx / n
        vb = sxx / n - mb * mb
        p1 = n1 / n
        if vb <= 0 or p1 in (0.0, 1.0):
            continue
        cov = s1 / n - (n1 / n) * mb
        r = cov / math.sqrt(vb * p1 * (1 - p1))
        mat[i, k] = mat[k, i] = abs(r)
    mat[k, k] = 1.0
    return {"vars": names, "labels_cn": labels, "matrix": [[None if np.isnan(x) else round(float(x), 4) for x in row] for row in mat],
            "detail_mm": detail}


# ---------------------------------------------------------------- Logistic
LOGIT_COLS = ["multimorbidity", "age", "sex", "race", "educa", "income_grp", "year",
              "smoker3", "obese", "phys_activity", "medcost", "persdoc", "checkup"]


def build_design(pdf: pd.DataFrame):
    """构造设计矩阵（含未知类哑变量，避免整行删除造成选择偏倚）。"""
    X = pd.DataFrame(index=pdf.index)
    display = {}

    age_c = pd.cut(pdf["age"], bins=[0, 45, 65, 75, 200], right=False,
                   labels=["age_18_44", "age_45_64", "age_65_74", "age_75p"])
    for lv in ["age_45_64", "age_65_74", "age_75p"]:
        X[lv] = (age_c == lv).astype("float32")
        display[lv] = {"18-44": "年龄 18-44（参照）"}.get(lv, "年龄 %s" % lv.split("_", 1)[1].replace("p", "+").replace("_", "-"))
    X["age_unknown"] = age_c.isna().astype("float32"); display["age_unknown"] = "年龄未知"

    X["sex_female"] = (pdf["sex"] == 2).astype("float32"); display["sex_female"] = "女性（对照：男性）"
    X["sex_unknown"] = pdf["sex"].isna().astype("float32"); display["sex_unknown"] = "性别未知"

    race_lab = pdf["race"].map({1: "white", 2: "black", 3: "aian", 4: "asian", 5: "nhpi",
                                6: "other", 7: "multi", 8: "hispanic"}).fillna("unknown")
    for lv, cn in [("black", "黑人"), ("asian", "亚裔"), ("hispanic", "西班牙裔"), ("other", "其他种族")]:
        X["race_" + lv] = (race_lab == lv).astype("float32")
        display["race_" + lv] = "种族：%s（对照：白人）" % cn
    X["race_unknown"] = (race_lab == "unknown").astype("float32"); display["race_unknown"] = "种族未知"

    edu_lab = pdf["educa"].map({1: "lt_hs", 2: "lt_hs", 3: "lt_hs", 4: "hs_ged",
                                5: "some_college", 6: "college"}).fillna("unknown")
    for lv, cn in [("hs_ged", "高中/GED"), ("some_college", "大学1-3年"), ("college", "大学4年+")]:
        X["educa_" + lv] = (edu_lab == lv).astype("float32")
        display["educa_" + lv] = "教育：%s（对照：≤初中）" % cn
    X["educa_unknown"] = (edu_lab == "unknown").astype("float32"); display["educa_unknown"] = "教育未知"

    inc_lab = pdf["income_grp"].map({1: "lt15k", 2: "15_25k", 3: "25_35k", 4: "35_50k", 5: "ge50k"}).fillna("unknown")
    for lv, cn in [("15_25k", "1.5-2.5万"), ("25_35k", "2.5-3.5万"), ("35_50k", "3.5-5万"), ("ge50k", "≥5万")]:
        X["income_" + lv] = (inc_lab == lv).astype("float32")
        display["income_" + lv] = "收入：%s（对照：<1.5万）" % cn
    X["income_unknown"] = (inc_lab == "unknown").astype("float32"); display["income_unknown"] = "收入未知"

    for y in (2020, 2021, 2022, 2023):
        X["year_%d" % y] = (pdf["year"] == y).astype("float32")
        display["year_%d" % y] = "调查年份 %d（对照：2019）" % y

    smoke_lab = pdf["smoker3"].map({1: "current", 2: "current", 3: "former", 4: "never"}).fillna("unknown")
    X["smoke_current"] = (smoke_lab == "current").astype("float32"); display["smoke_current"] = "现吸烟（对照：从不吸烟）"
    X["smoke_former"] = (smoke_lab == "former").astype("float32"); display["smoke_former"] = "曾经吸烟（对照：从不吸烟）"
    X["smoke_unknown"] = (smoke_lab == "unknown").astype("float32"); display["smoke_unknown"] = "吸烟状态未知"

    X["obese"] = (pdf["obese"] == 1).astype("float32"); display["obese"] = "肥胖 BMI≥30（对照：非肥胖）"
    X["obese_unknown"] = pdf["obese"].isna().astype("float32"); display["obese_unknown"] = "BMI 未知"

    X["phys_inactive"] = (pdf["phys_activity"] == 0).astype("float32"); display["phys_inactive"] = "无闲暇体力活动（对照：有）"
    X["phys_unknown"] = pdf["phys_activity"].isna().astype("float32"); display["phys_unknown"] = "体力活动未知"

    X["cost_barrier"] = (pdf["medcost"] == 1).astype("float32"); display["cost_barrier"] = "因费用未就医（对照：否）"
    X["cost_unknown"] = pdf["medcost"].isna().astype("float32"); display["cost_unknown"] = "费用障碍未知"

    X["no_doctor"] = (pdf["persdoc"] == 3).astype("float32"); display["no_doctor"] = "无固定就诊医生（对照：有）"
    X["doctor_unknown"] = pdf["persdoc"].isna().astype("float32"); display["doctor_unknown"] = "固定医生未知"

    X["no_checkup_1y"] = pdf["checkup"].isin([2, 3, 4, 8]).astype("float32")
    display["no_checkup_1y"] = "超过 1 年未体检（对照：1 年内）"
    X["checkup_unknown"] = pdf["checkup"].isna().astype("float32"); display["checkup_unknown"] = "体检未知"

    X.insert(0, "const", np.float32(1.0))
    display["const"] = "截距"
    return X, display


def fit_logit(X: pd.DataFrame, y: np.ndarray):
    """拟合多因素 Logistic 回归。

    哑变量之间可能存在完全共线，导致设计矩阵秩亏（statsmodels 只告警，
    但此时部分系数不可识别，OR 不可解释）。这里先用带主元的 QR 在抽样上
    判定数值秩，剔除共线列后再用全量数据拟合。
    """
    from scipy.linalg import qr

    n = len(X)
    if n > 200000:
        idx = np.random.RandomState(42).choice(n, 200000, replace=False)
        sample = X.iloc[idx]
    else:
        sample = X
    arr = np.asarray(sample.to_numpy(dtype=np.float64), order="F")
    _, R, piv = qr(arr, pivoting=True, mode="economic")
    d = np.abs(np.diag(R))
    tol = d[0] * 1e-10 if (d.size and d[0] > 0) else 0.0
    rank = int((d > tol).sum())
    keep = sorted(int(i) for i in piv[:rank])
    dropped = [c for i, c in enumerate(X.columns) if i not in set(keep)]
    if dropped:
        log("  秩亏修复：剔除 %d 个共线/常数列 %s" % (len(dropped), dropped))
    Xk = X.iloc[:, keep]
    model = sm.GLM(y, Xk, family=sm.families.Binomial())
    res = model.fit(maxiter=100, disp=0)
    try:
        res._kept_columns = list(Xk.columns)
    except Exception:
        pass
    return res


# ---------------------------------------------------------------- 主流程
def main() -> int:
    t0 = time.time()
    os.makedirs(FIG_DIR, exist_ok=True)
    os.makedirs(MET_DIR, exist_ok=True)
    spark = spark_session()
    log("Spark %s 启动完成（local[8]，driver 4g）" % spark.version)

    n_total = spark.read.parquet(PROCESSED).count()
    log("清洗后总行数 %d" % n_total)

    # ============================================================ A1 逐年各慢病患病率
    cols = ["year", "multimorbidity", "chronic_count"] + [c for c, _ in DISEASES]
    df = load(spark, cols)
    exprs = [F.count(F.lit(1)).alias("__n")]
    for c, _ in DISEASES:
        exprs += [F.sum(F.when(F.col(c) == 1, 1).otherwise(0)).alias(c + "__pos"),
                  F.count(F.col(c)).alias(c + "__den")]
    exprs += [F.sum(F.col("multimorbidity")).alias("mm__pos"),
              F.sum(F.col("chronic_count")).alias("cc__sum"),
              F.sum(F.when(F.col("chronic_count") >= 3, 1).otherwise(0)).alias("cc3__pos")]
    rows = df.groupBy("year").agg(*exprs).orderBy("year").collect()
    yearly = {}
    for r in rows:
        d = r.asDict()
        y = int(d["year"])
        item = {"n": int(d["__n"])}
        for c, _ in DISEASES:
            item[c] = {"n_valid": int(d[c + "__den"]), "n_positive": int(d[c + "__pos"]),
                       "rate": round(d[c + "__pos"] / d[c + "__den"], 6) if d[c + "__den"] else None}
        item["multimorbidity"] = {"n_valid": int(d["__n"]), "n_positive": int(d["mm__pos"]),
                                  "rate": round(d["mm__pos"] / d["__n"], 6)}
        item["chronic_count_mean"] = round(d["cc__sum"] / d["__n"], 4)
        item["chronic_count_ge3_rate"] = round(d["cc3__pos"] / d["__n"], 6)
        yearly[str(y)] = item
    log("A1 逐年患病率完成")

    # 全样本合并患病率 + Wilson 95%CI（描述统计用）
    overall = {}
    for c, cn in DISEASES + [("multimorbidity", "共病（慢病数≥2）")]:
        pos = sum(yearly[str(y)][c]["n_positive"] for y in YEARS)
        den = sum(yearly[str(y)][c]["n_valid"] for y in YEARS)
        p = pos / den
        se = math.sqrt(p * (1 - p) / den)
        overall[c] = {"name_cn": cn, "n_positive": pos, "n_valid": den, "rate": round(p, 6),
                      "ci95": [round(p - 1.96 * se, 6), round(p + 1.96 * se, 6)]}

    # ============================================================ A2 chronic_count 分布
    dist_rows = load(spark, ["year", "chronic_count"]).groupBy("year", "chronic_count").count().collect()
    cc_dist = {str(y): {str(k): 0 for k in range(9)} for y in YEARS}
    for r in dist_rows:
        cc_dist[str(int(r["year"]))][str(int(r["chronic_count"]))] = int(r["count"])
    cc_overall = {str(k): sum(int(cc_dist[str(y)][str(k)]) for y in YEARS) for k in range(9)}
    cc_overall_pct = {k: round(100 * v / n_total, 4) for k, v in cc_overall.items()}
    log("A2 chronic_count 分布完成")

    # ============================================================ A3 分层共病率
    strata = {}
    dims = [("age_grp", AGE_GRP_LABEL), ("sex", SEX_LABEL), ("income_grp", INCOME_LABEL),
            ("educa", EDUCA_LABEL), ("state_fips", None)]
    for dim, labels in dims:
        rows = (load(spark, [dim, "multimorbidity"])
                .groupBy(dim)
                .agg(F.count(F.lit(1)).alias("n"), F.sum(F.col("multimorbidity")).alias("pos"))
                .collect())
        items = []
        for r in rows:
            code = r[dim]
            if code is None:
                continue
            lab = labels.get(int(code)) if labels else STATE_FALLBACK.get(int(code), str(int(code)))
            items.append({"code": int(code), "label": lab, "n": int(r["n"]),
                          "n_multimorbidity": int(r["pos"]),
                          "rate": round(r["pos"] / r["n"], 6) if r["n"] else None})
        items.sort(key=lambda x: x["code"])
        strata[dim] = items
    log("A3 分层共病率完成（%d 个维度）" % len(strata))

    # 用库内 dim_state 覆盖州缩写（单一事实来源优先）
    if os.path.exists(DB_PATH):
        try:
            con = sqlite3.connect(DB_PATH)
            names = {int(r[0]): (r[1] or r[2]) for r in con.execute("SELECT state_fips, state_abbr, state_name FROM dim_state")}
            con.close()
            for it in strata["state_fips"]:
                it["label"] = names.get(it["code"], it["label"])
        except sqlite3.Error as exc:
            log("  读取 dim_state 失败（用内置映射）：%s" % exc)

    # ============================================================ A4 危险因素暴露率 + 共病率
    rf_defs = [
        ("obese", "肥胖(BMI≥30)", "obese", 1),
        ("smoke_current", "现吸烟", "smoker3", None),
        ("phys_inactive", "无体力活动", "phys_activity", 0),
        ("cost_barrier", "因费用未就医", "medcost", 1),
        ("no_doctor", "无固定医生", "persdoc", None),
        ("no_checkup_1y", "超1年未体检", "checkup", None),
        ("diffwalk", "行走困难", "diffwalk", 1),
        ("heavy_drink", "暴饮(2022+)", "heavy_drink", 1),
    ]
    exprs_by_year = load(spark, ["year", "obese", "smoker3", "phys_activity", "medcost", "persdoc",
                                 "checkup", "diffwalk", "heavy_drink", "multimorbidity"])
    rf_expr = {
        "obese": F.when(F.col("obese") == 1, F.lit(1)).when(F.col("obese") == 0, F.lit(0)).otherwise(F.lit(None).cast("int")),
        "smoke_current": F.when(F.col("smoker3").isin(1, 2), F.lit(1)).when(F.col("smoker3").isin(3, 4), F.lit(0)).otherwise(F.lit(None).cast("int")),
        "phys_inactive": F.when(F.col("phys_activity").isNull(), F.lit(None).cast("int")).otherwise(1 - F.col("phys_activity")),
        "cost_barrier": F.when(F.col("medcost") == 1, F.lit(1)).when(F.col("medcost") == 0, F.lit(0)).otherwise(F.lit(None).cast("int")),
        "no_doctor": F.when(F.col("persdoc") == 3, F.lit(1)).when(F.col("persdoc").isin(1, 2), F.lit(0)).otherwise(F.lit(None).cast("int")),
        "no_checkup_1y": F.when(F.col("checkup").isin(2, 3, 4, 8), F.lit(1)).when(F.col("checkup") == 1, F.lit(0)).otherwise(F.lit(None).cast("int")),
        "diffwalk": F.when(F.col("diffwalk") == 1, F.lit(1)).when(F.col("diffwalk") == 0, F.lit(0)).otherwise(F.lit(None).cast("int")),
        "heavy_drink": F.when(F.col("heavy_drink") == 1, F.lit(1)).when(F.col("heavy_drink") == 0, F.lit(0)).otherwise(F.lit(None).cast("int")),
    }
    agg_exprs = []
    for k, e in rf_expr.items():
        agg_exprs += [
            F.sum(F.when(e == 1, 1).otherwise(0)).alias(k + "__pos"),
            F.count(e).alias(k + "__den"),
            F.sum(F.when((e == 1) & (F.col("multimorbidity") == 1), 1).otherwise(0)).alias(k + "__mm"),
            F.count(F.when(e.isNotNull(), F.col("multimorbidity"))).alias(k + "__mmden"),
        ]
    rf_rows = exprs_by_year.groupBy("year").agg(*agg_exprs).orderBy("year").collect()
    rf_by_year = {}
    for r in rf_rows:
        d = r.asDict()
        y = str(int(d["year"]))
        rf_by_year[y] = {}
        for k, _ in [(k, v) for k, v, *_ in rf_defs]:
            den = int(d[k + "__den"])
            rf_by_year[y][k] = {"n_valid": den, "n_positive": int(d[k + "__pos"]),
                                "rate": round(d[k + "__pos"] / den, 6) if den else None,
                                "mm_rate_exposed": round(d[k + "__mm"] / d[k + "__mmden"], 6) if d[k + "__mmden"] else None}
    log("A4 危险因素暴露率完成")

    # ============================================================ A5 关联矩阵（精确联合分布）
    pdf_joint = joint_table(spark)
    assoc = association_matrix(pdf_joint)
    log("A5 关联矩阵完成（%d 个变量）" % len(assoc["vars"]))

    # ============================================================ A6 加权对照（_LLCPWT）
    frames = []
    for y in YEARS:
        p = os.path.join(RAW_DIR, "LLCP%d.parquet" % y)
        s = spark.read.parquet(p).select(
            F.concat_ws("_", F.lit(y).cast("string"), F.col("_STSTR").cast("int").cast("string"),
                        F.col("SEQNO").cast("int").cast("string")).alias("seq_key"),
            F.col("_LLCPWT").cast("double").alias("weight"))
        frames.append(s)
    w = frames[0]
    for f in frames[1:]:
        w = w.unionByName(f)
    clean_keys = load(spark, ["seq_key", "year", "multimorbidity"] + [c for c, _ in DISEASES])
    cw = clean_keys.join(w, "seq_key", "inner")
    wexprs = [F.count(F.lit(1)).alias("__n"), F.sum("weight").alias("__w")]
    for c, _ in DISEASES:
        wexprs += [F.sum(F.when(F.col(c) == 1, F.col("weight")).otherwise(F.lit(0.0))).alias(c + "__wpos"),
                   F.sum(F.when(F.col(c).isNotNull(), F.col("weight")).otherwise(F.lit(0.0))).alias(c + "__wden"),
                   F.sum(F.when(F.col(c) == 1, 1).otherwise(0)).alias(c + "__pos"),
                   F.count(F.col(c)).alias(c + "__den")]
    wexprs += [F.sum(F.when(F.col("multimorbidity") == 1, F.col("weight")).otherwise(F.lit(0.0))).alias("mm__wpos"),
               F.sum(F.col("multimorbidity")).alias("mm__pos")]
    wr = cw.groupBy("year").agg(*wexprs).orderBy("year").collect()
    weighted = {}
    n_weighted_total = 0
    wsum_total = 0.0
    for r in wr:
        d = r.asDict()
        y = str(int(d["year"]))
        n = int(d["__n"]); wsum = float(d["__w"])
        n_weighted_total += n; wsum_total += wsum
        items = {}
        for c, cn in DISEASES:
            wden = float(d[c + "__wden"]) or 1.0
            items[c] = {"weighted_rate": round(float(d[c + "__wpos"]) / wden, 6),
                        "unweighted_rate": round(d[c + "__pos"] / d[c + "__den"], 6) if d[c + "__den"] else None}
        items["multimorbidity"] = {"weighted_rate": round(float(d["mm__wpos"]) / wsum, 6),
                                   "unweighted_rate": round(d["mm__pos"] / n, 6)}
        weighted[y] = {"n": n, "weight_sum": round(wsum, 2), "mean_weight": round(wsum / n, 3), "items": items}
    if n_weighted_total != n_total:
        raise RuntimeError("权重 join 行数不一致：%d != %d（seq_key 口径错位）" % (n_weighted_total, n_total))
    log("A6 加权对照完成（权重总和 %.1f 亿，平均权重 %.1f，join 行数校验通过）"
        % (wsum_total / 1e8, wsum_total / n_weighted_total))

    # ============================================================ A7 剂量-反应（可干预因素个数）
    dr_df = load(spark, ["obese", "smoker3", "phys_activity", "multimorbidity"])
    sm = F.when(F.col("smoker3").isin(1, 2), F.lit(1)).when(F.col("smoker3").isin(3, 4), F.lit(0)).otherwise(F.lit(None).cast("int"))
    inact = F.when(F.col("phys_activity").isNull(), F.lit(None).cast("int")).otherwise(1 - F.col("phys_activity"))
    n_risk = (F.when(F.col("obese").isNull(), F.lit(None).cast("int")).otherwise(F.col("obese"))
              + sm + inact)
    dr_rows = (dr_df.withColumn("n_risk", n_risk).filter(F.col("n_risk").isNotNull())
                    .groupBy("n_risk")
                    .agg(F.count(F.lit(1)).alias("n"), F.sum(F.col("multimorbidity")).alias("pos"))
                    .orderBy("n_risk").collect())
    dose_response = [{"n_risk": int(r["n_risk"]), "n": int(r["n"]), "n_multimorbidity": int(r["pos"]),
                      "rate": round(r["pos"] / r["n"], 6)} for r in dr_rows]
    log("A7 剂量-反应完成：%s" % [(d["n_risk"], d["rate"]) for d in dose_response])

    # ============================================================ C 假设验证：多因素 Logistic
    t_lr = time.time()
    pdf = load(spark, LOGIT_COLS).toPandas()
    for c in ["multimorbidity", "age", "sex", "race", "educa", "income_grp", "year",
              "smoker3", "obese", "phys_activity", "medcost", "persdoc", "checkup"]:
        pdf[c] = pd.to_numeric(pdf[c], errors="coerce").astype("float64")
    y = pdf["multimorbidity"].to_numpy(dtype="float64")
    X, display = build_design(pdf)
    X = X.astype("float64")
    log("  Logistic 设计矩阵：%d 行 × %d 列，事件率 %.4f" % (X.shape[0], X.shape[1], y.mean()))
    used_full = True
    try:
        res = fit_logit(X, y)
    except MemoryError:  # pragma: no cover - 内存不足时固定种子抽样，报告 n
        used_full = False
        rng = np.random.default_rng(2024)
        idx = np.sort(rng.choice(len(y), size=800_000, replace=False))
        X, y = X.iloc[idx], y[idx]
        res = fit_logit(X, y)
        log("  内存不足，改用 80 万随机样本拟合（seed=2024）")
    ci = res.conf_int()
    terms = []
    for name in res.params.index:  # 用实际入模列，剪枝剔除的列不会出现在这里
        if name == "const":
            continue
        coef = float(res.params[name]); se = float(res.bse[name]); p = float(res.pvalues[name])
        lo, hi = float(ci[0][name]), float(ci[1][name])
        terms.append({"term": name, "term_cn": display.get(name, name),
                      "coef": round(coef, 6), "se": round(se, 6),
                      "or": round(math.exp(coef), 4),
                      "or_ci_low": round(math.exp(lo), 4), "or_ci_high": round(math.exp(hi), 4),
                      "z": round(float(res.tvalues[name]), 3), "p_value": p,
                      "significant": bool(hi < 0 or lo > 0)})
    dev_null = float(res.null_deviance); dev = float(res.deviance)
    pseudo_r2 = 1 - dev / dev_null
    adjustable = ["smoke_current", "smoke_former", "obese", "phys_inactive",
                  "cost_barrier", "no_doctor", "no_checkup_1y"]
    ranking = sorted([t for t in terms if t["term"] in adjustable], key=lambda t: -t["or"])
    logistic = {
        "method": "statsmodels GLM(Binomial) IRLS，全变量同时纳入（未逐步筛选）",
        "n": int(X.shape[0]), "n_rows_available": int(len(y)), "used_full_sample": used_full,
        "n_terms": int(X.shape[1]), "n_events": int(y.sum()), "event_rate": round(float(y.mean()), 6),
        "aic": round(float(res.aic), 2), "deviance": round(dev, 2), "null_deviance": round(dev_null, 2),
        "mcfadden_pseudo_r2": round(pseudo_r2, 6),
        "terms": terms, "ranking_adjustable_by_or": ranking,
        "fit_seconds": round(time.time() - t_lr, 1),
    }
    # 仅含"完全可干预"因素 + 必需混杂的模型（供报告强调可干预性）
    log("  多因素 Logistic 完成：McFadden R²=%.4f，AIC=%.1f" % (pseudo_r2, float(res.aic)))

    # 联合暴露（3 个可干预生活方式因素）调整后 OR：用哑变量计数分段
    pdf["n_life_risk"] = ((pdf["obese"] == 1).astype(int)
                          + pdf["smoker3"].isin([1, 2]).astype(int)
                          + (pdf["phys_activity"] == 0).astype(int))
    complete = (pdf["obese"].notna() & pdf["smoker3"].notna() & pdf["phys_activity"].notna())
    X2 = X.copy()
    for lv in (1, 2, 3):
        X2["life_risk_%d" % lv] = ((pdf["n_life_risk"] == lv) & complete).astype("float64")
        display["life_risk_%d" % lv] = "可干预生活方式因素 %d 个（对照：0 个）" % lv
    res2 = fit_logit(X2, y)
    ci2 = res2.conf_int()
    joint_terms = []
    for lv in (1, 2, 3):
        name = "life_risk_%d" % lv
        joint_terms.append({"term": name, "term_cn": display[name],
                            "or": round(math.exp(float(res2.params[name])), 4),
                            "or_ci_low": round(math.exp(float(ci2[0][name])), 4),
                            "or_ci_high": round(math.exp(float(ci2[1][name])), 4),
                            "p_value": float(res2.pvalues[name])})
    logistic["joint_lifestyle_terms"] = joint_terms
    log("  联合暴露模型完成：OR=%s" % [(t["term"], t["or"]) for t in joint_terms])

    # ============================================================ 图 1-12
    # 1 各慢病患病率
    fig, ax = plt.subplots(figsize=(9, 5))
    names = [DISEASES[i][1] for i in range(len(DISEASES))]
    vals = [overall[c]["rate"] * 100 for c, _ in DISEASES]
    order = np.argsort(vals)
    ax.barh([names[i] for i in order], [vals[i] for i in order], color=PALETTE[0])
    for i, idx in enumerate(order):
        ax.text(vals[idx] + 0.25, i, "%.2f%%" % vals[idx], va="center", fontsize=8.5)
    ax.set_xlabel("患病率（%）")
    ax.set_title("八种慢性病患病率（2019–2023 合并，n=2,136,402）")
    ax.set_xlim(0, max(vals) * 1.2)
    save_fig(fig, "disease_prevalence.png",
             "口径：患病率=该病标志位=1 的样本数/该标志位非缺失样本数（未加权），单位 %；各病分母略有差异（见 eda_metrics.json）。")

    # 2 逐年趋势
    fig, ax = plt.subplots(figsize=(9, 5.2))
    for i, (c, cn) in enumerate(DISEASES):
        ax.plot(YEARS, [yearly[str(y)][c]["rate"] * 100 for y in YEARS], marker="o", ms=4,
                lw=1.8, color=PALETTE[i % len(PALETTE)], label=cn)
    ax.plot(YEARS, [yearly[str(y)]["multimorbidity"]["rate"] * 100 for y in YEARS], marker="s",
            ms=6, lw=2.6, color="#111111", ls="--", label="共病(≥2种)")
    ax.axvspan(2019.6, 2021.4, color="#cccccc", alpha=0.35, label="COVID-19 年份(2020–2021)")
    ax.set_xticks(YEARS)
    ax.set_xlabel("调查年份")
    ax.set_ylabel("患病率（%）")
    ax.set_title("慢病患病率年度趋势（2019→2023）")
    ax.legend(ncol=2, fontsize=8)
    save_fig(fig, "yearly_trend.png",
             "口径：各年横截面患病率（未加权），单位 %；灰底为 COVID-19 相关年份（自报口径，非临床诊断口径）。")

    # 3 chronic_count 分布
    fig, ax = plt.subplots(figsize=(8.5, 5))
    ks = [str(k) for k in range(9)]
    v = [cc_overall[k] for k in ks]
    colors = ["#4c9f70" if k < 2 else ("#e0a43a" if k == 2 else "#b3403a") for k in range(9)]
    bars = ax.bar(ks, v, color=colors)
    for b, k in zip(bars, ks):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 8000, "%.2f%%" % cc_overall_pct[k],
                ha="center", fontsize=8.5)
    ax.set_xlabel("慢性病种数 chronic_count")
    ax.set_ylabel("样本数（人）")
    ax.set_title("慢性病共病数量分布（n=2,136,402）")
    save_fig(fig, "chronic_count_dist.png",
             "口径：chronic_count=8 个慢病标志位之和（缺失位按 0 计）；绿色=0–1 种，橙色=2 种（共病阈值），红色=≥3 种；单位 人/% 。")

    # 4 共病率-年龄
    fig, ax = plt.subplots(figsize=(9, 5))
    it = strata["age_grp"]
    ax.bar([i["label"] for i in it], [i["rate"] * 100 for i in it], color=PALETTE[0])
    for i, x in enumerate(it):
        ax.text(x=i, y=x["rate"] * 100 + 0.8, s="%.1f" % (x["rate"] * 100), ha="center", fontsize=7.5)
    ax.set_xlabel("年龄组（_AGEG5YR）")
    ax.set_ylabel("共病率（%）")
    ax.set_title("共病率随年龄组的变化")
    ax.tick_params(axis="x", labelrotation=45)
    save_fig(fig, "comorbidity_by_age.png",
             "口径：共病率=chronic_count≥2 的比例（未加权），n=2,136,402，单位 %。")

    # 5 共病率-收入
    fig, ax = plt.subplots(figsize=(8.5, 5))
    it = strata["income_grp"]
    ax.bar([i["label"] for i in it], [i["rate"] * 100 for i in it], color=PALETTE[2])
    for i, x in enumerate(it):
        ax.text(x=i, y=x["rate"] * 100 + 0.5, s="%.2f%%" % (x["rate"] * 100), ha="center", fontsize=8.5)
    ax.set_xlabel("家庭年收入组（美元）")
    ax.set_ylabel("共病率（%）")
    ax.set_title("共病率的社会经济梯度（收入）")
    save_fig(fig, "comorbidity_by_income.png",
             "口径：共病率未加权；收入为 _INCOMG 五档（2019–2023 调和），缺失不入图，单位 %。")

    # 6 共病率-教育
    fig, ax = plt.subplots(figsize=(8.5, 5))
    it = strata["educa"]
    ax.bar([i["label"] for i in it], [i["rate"] * 100 for i in it], color=PALETTE[4])
    for i, x in enumerate(it):
        ax.text(x=i, y=x["rate"] * 100 + 0.5, s="%.2f%%" % (x["rate"] * 100), ha="center", fontsize=8.5)
    ax.set_xlabel("教育程度（EDUCA）")
    ax.set_ylabel("共病率（%）")
    ax.set_title("共病率的社会经济梯度（教育）")
    ax.tick_params(axis="x", labelrotation=20)
    save_fig(fig, "comorbidity_by_education.png",
             "口径：共病率未加权；教育为 EDUCA 六档，缺失不入图，单位 %。")

    # 7 州级热力色阶
    st = sorted([x for x in strata["state_fips"] if x["n"] >= 1000], key=lambda x: -x["rate"])
    fig, ax = plt.subplots(figsize=(13, 5.2))
    cmap = plt.get_cmap("RdYlBu_r")
    norm = plt.Normalize(min(x["rate"] for x in st) * 100, max(x["rate"] for x in st) * 100)
    ax.bar([x["label"] for x in st], [x["rate"] * 100 for x in st],
           color=[cmap(norm(x["rate"] * 100)) for x in st])
    ax.set_ylabel("共病率（%）")
    ax.set_title("各州共病率（热力色阶，按降序）")
    ax.tick_params(axis="x", labelrotation=90, labelsize=7)
    sm_ = plt.cm.ScalarMappable(cmap=cmap, norm=norm); sm_.set_array([])
    fig.colorbar(sm_, ax=ax, label="共病率（%）")
    save_fig(fig, "state_heatmap.png",
             "口径：州级共病率未加权（仅纳入 n≥1000 的辖区），n=2,136,402，单位 %；州名缩写见 dim_state。")

    # 8 危险因素分组对比
    fig, ax = plt.subplots(figsize=(10, 5.4))
    keys = ["smoke_current", "obese", "phys_inactive", "cost_barrier", "no_doctor", "no_checkup_1y", "diffwalk"]
    cn = {"smoke_current": "现吸烟", "obese": "肥胖", "phys_inactive": "无体力活动",
          "cost_barrier": "费用障碍", "no_doctor": "无固定医生", "no_checkup_1y": "超1年未体检",
          "diffwalk": "行走困难"}
    exp_rate, unexp_rate = [], []
    for k in keys:
        d = assoc["detail_mm"][k]
        exp_rate.append(d["rate_exposed"] * 100)
        unexp_rate.append(d["rate_unexposed"] * 100)
    x = np.arange(len(keys)); wd = 0.38
    ax.bar(x - wd / 2, exp_rate, wd, label="暴露组", color=PALETTE[3])
    ax.bar(x + wd / 2, unexp_rate, wd, label="非暴露组", color=PALETTE[0])
    for i, (a_, b_) in enumerate(zip(exp_rate, unexp_rate)):
        ax.text(i - wd / 2, a_ + 0.6, "%.1f" % a_, ha="center", fontsize=7.6)
        ax.text(i + wd / 2, b_ + 0.6, "%.1f" % b_, ha="center", fontsize=7.6)
    ax.set_xticks(x); ax.set_xticklabels([cn[k] for k in keys], rotation=18)
    ax.set_ylabel("共病率（%）"); ax.set_title("危险因素暴露组 vs 非暴露组的共病率")
    ax.legend()
    save_fig(fig, "risk_factor_grouped.png",
             "口径：分组共病率未加权；每组 n 与非暴露组 OR 见 hypothesis_metrics.json；单位 %。")

    # 9 关联矩阵热力图
    names_cn = assoc["labels_cn"]
    m = np.array([[np.nan if v is None else v for v in row] for row in assoc["matrix"]], dtype=float)
    fig, ax = plt.subplots(figsize=(9.6, 8))
    im = ax.imshow(m, cmap="YlOrRd", vmin=0, vmax=0.6)
    ax.set_xticks(range(len(names_cn))); ax.set_yticks(range(len(names_cn)))
    ax.set_xticklabels(names_cn, rotation=45, ha="right", fontsize=8.5)
    ax.set_yticklabels(names_cn, fontsize=8.5)
    for i in range(m.shape[0]):
        for j in range(m.shape[1]):
            if not np.isnan(m[i, j]):
                ax.text(j, i, "%.2f" % m[i, j], ha="center", va="center", fontsize=6.6,
                        color="white" if m[i, j] > 0.36 else "#222222")
    ax.grid(False)
    fig.colorbar(im, ax=ax, label="关联强度（|Cramér's V| 或 |r_pb|）")
    ax.set_title("危险因素与共病的关联矩阵（Cramér's V / 点二列相关）")
    save_fig(fig, "correlation_heatmap.png",
             "口径：二值×二值为 Cramér's V（=|φ|），BMI×二值为点二列相关 |r|；由 14 个二值变量的精确联合分布计算（n=2,136,402，无抽样）。")

    # 10 加权 vs 未加权
    fig, ax = plt.subplots(figsize=(9, 5.2))
    x = np.arange(len(YEARS)); wd = 0.27
    uw = [yearly[str(y)]["multimorbidity"]["rate"] * 100 for y in YEARS]
    ww = [weighted[str(y)]["items"]["multimorbidity"]["weighted_rate"] * 100 for y in YEARS]
    ax.bar(x - wd / 2, uw, wd, label="未加权抽样比例", color=PALETTE[0])
    ax.bar(x + wd / 2, ww, wd, label="加权（_LLCPWT）", color=PALETTE[1])
    for i in range(len(YEARS)):
        ax.text(i - wd / 2, uw[i] + 0.12, "%.2f" % uw[i], ha="center", fontsize=8)
        ax.text(i + wd / 2, ww[i] + 0.12, "%.2f" % ww[i], ha="center", fontsize=8)
    ax.set_xticks(x); ax.set_xticklabels(YEARS)
    ax.set_xlabel("调查年份"); ax.set_ylabel("共病率（%）")
    ax.set_title("共病率：未加权抽样比例 vs 设计加权估计")
    ax.legend()
    save_fig(fig, "weighted_vs_unweighted.png",
             "口径：加权=Σ(_LLCPWT×I(共病))/Σ_LLCPWT，未加权=共病人数/样本数；_LLCPWT 为 CDC 最终设计权重，单位 %。")

    # 11 调整后 OR 森林图
    fig, ax = plt.subplots(figsize=(9.4, 7.6))
    show = ["smoke_former", "smoke_current", "obese", "phys_inactive", "cost_barrier", "no_doctor",
            "no_checkup_1y", "educa_hs_ged", "educa_some_college", "educa_college",
            "income_15_25k", "income_25_35k", "income_35_50k", "income_ge50k"]
    tmap = {t["term"]: t for t in terms}
    ys = []
    for i, k in enumerate(show):
        t = tmap[k]
        ys.append(i)
        color = PALETTE[3] if t["or"] > 1 else PALETTE[0]
        ax.plot([t["or_ci_low"], t["or_ci_high"]], [i, i], color=color, lw=2.2)
        ax.plot(t["or"], i, "o", color=color, ms=6)
        ax.text(ax.get_xlim()[1] if False else t["or_ci_high"] * 1.03, i,
                "OR=%.2f [%.2f, %.2f]" % (t["or"], t["or_ci_low"], t["or_ci_high"]),
                va="center", fontsize=7.4)
    ax.axvline(1.0, color="#666666", ls="--", lw=1)
    ax.set_xscale("log")
    ax.set_yticks(ys); ax.set_yticklabels([display[k] for k in show], fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("调整后 OR（对数刻度，95%CI）")
    ax.set_title("多因素 Logistic 回归：调整后 OR（n=%d）" % logistic["n"])
    ax.set_xlim(0.2, 12)
    save_fig(fig, "or_forest.png",
             "口径：调整年龄/性别/种族/教育/收入/年份后的 OR 与 95%CI（statsmodels GLM-Binomial，全变量同时纳入）；参照组见纵轴说明；OR>1 为风险升高。")

    # 12 剂量-反应
    fig, ax = plt.subplots(figsize=(8.4, 5))
    xs = [d["n_risk"] for d in dose_response]
    ys2 = [d["rate"] * 100 for d in dose_response]
    ax.plot(xs, ys2, marker="o", lw=2.4, color=PALETTE[3])
    for a_, b_ in zip(xs, ys2):
        ax.text(a_, b_ + 0.7, "%.1f%%" % b_, ha="center", fontsize=9)
    ax.set_xticks(xs)
    ax.set_xlabel("可干预生活方式危险因素个数（肥胖+现吸烟+无体力活动）")
    ax.set_ylabel("共病率（%）")
    ax.set_title("可干预风险因素的剂量-反应关系")
    save_fig(fig, "dose_response.png",
             "口径：仅纳入三项生活方式变量全部非缺失的样本，共病率未加权，单位 %；每点 n 见 hypothesis_metrics.json。")

    # ============================================================ 写 JSON
    eda = {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "engine": "pyspark %s (local[8])" % __import__("pyspark").__version__,
        "source": "data/processed/brfss_clean.parquet（由 02_clean_spark.py 生成）",
        "n_total": int(n_total),
        "years": YEARS,
        "n_by_year": {str(y): yearly[str(y)]["n"] for y in YEARS},
        "overall_prevalence": overall,
        "yearly_prevalence": yearly,
        "chronic_count_dist": {"overall": cc_overall, "overall_pct": cc_overall_pct, "by_year": cc_dist},
        "strata": strata,
        "risk_factor_exposure_by_year": rf_by_year,
        "association": assoc,
        "weighted_vs_unweighted": {
            "by_year": weighted,
            "note": "加权使用 CDC 最终设计权重 _LLCPWT（原始 parquet），未加权为样本内比例；"
                    "差异方向反映 BRFSS 抽样对高龄/低教育人群的低估程度。",
        },
        "notes": [
            "患病率单位一律为 %，小数位 4 位；n 为该指标的有效分母。",
            "慢性病标志位 1=有；7=不知道/9=拒答已在清洗阶段置 NULL。",
            "共病 multimorbidity = chronic_count>=2。",
        ],
    }
    with open(EDA_JSON, "w", encoding="utf-8") as f:
        json.dump(eda, f, ensure_ascii=False, indent=2)
    log("已写出 %s" % EDA_JSON)

    # 假设检验结论（数据驱动，但方向在跑之前已固定）
    dt = assoc["detail_mm"]
    h1_ok = all(dt[k]["or_crude"] and dt[k]["or_crude"] > 1 for k in ["smoke_current", "obese", "phys_inactive"])
    adj = {t["term"]: t for t in terms}
    h1_adj = all(adj[k]["or"] > 1 and adj[k]["or_ci_low"] > 1
                 for k in ["smoke_current", "obese", "phys_inactive"])
    h2_mono = (strata["income_grp"][0]["rate"] > strata["income_grp"][-1]["rate"])
    h3_sig = adj["cost_barrier"]["or_ci_low"] > 1 or adj["no_doctor"]["or_ci_low"] > 1
    hyp = {
        "generated_at": eda["generated_at"],
        "n_total": int(n_total),
        "method_A": "分组对比 + 多因素 Logistic 回归（调整年龄/性别/种族/教育/收入/年份）",
        "method_B": "卡方检验（2x2）+ Cramér's V 效应量；n 极大时以效应量而非 p 值判断",
        "grouped_comparison": dt,
        "multivariable_logistic": logistic,
        "dose_response_lifestyle": dose_response,
        "income_gradient": strata["income_grp"],
        "education_gradient": strata["educa"],
        "hypothesis_verdict": {
            "H1_crude_or_gt1": bool(h1_ok),
            "H1_adjusted_significant": bool(h1_adj),
            "H2_income_gradient_present": bool(h2_mono),
            "H2_adjusted_income_or": {"income_ge50k": adj["income_ge50k"]["or"],
                                      "educa_college": adj["educa_college"]["or"]},
            "H3_at_least_one_access_sig": bool(h3_sig),
            "H3_cost_barrier_or": adj["cost_barrier"]["or"],
            "H3_no_doctor_or": adj["no_doctor"]["or"],
            "H3_no_checkup_or": adj["no_checkup_1y"]["or"],
        },
    }
    with open(HYP_JSON, "w", encoding="utf-8") as f:
        json.dump(hyp, f, ensure_ascii=False, indent=2)
    log("已写出 %s" % HYP_JSON)

    elapsed = round(time.time() - t0, 1)
    step = {"step": "03_eda_spark", "label": "PySpark EDA + 假设验证",
            "started_at": datetime.fromtimestamp(t0).astimezone().isoformat(timespec="seconds"),
            "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "elapsed_sec": elapsed, "engine": "pyspark %s local[8]" % __import__("pyspark").__version__,
            "rows_in": int(n_total), "rows_out": int(n_total),
            "detail": json.dumps({"figures": 12, "association_vars": len(assoc["vars"]),
                                  "logistic_n": logistic["n"],
                                  "logistic_r2": logistic["mcfadden_pseudo_r2"]}, ensure_ascii=False)}
    data = {"steps": []}
    if os.path.exists(LOG_PATH):
        try:
            with open(LOG_PATH, encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError:
            data = {"steps": []}
    data.setdefault("steps", [])
    data["generated_at"] = eda["generated_at"]
    data["steps"] = [s for s in data["steps"] if s.get("step") != step["step"]] + [step]
    with open(LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    spark.stop()
    log("03_eda_spark 完成，总耗时 %.1f 秒" % elapsed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
