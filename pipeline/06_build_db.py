# -*- coding: utf-8 -*-
"""06_build_db.py —— 构建 SQLite 分析库

流程：
  1. 建库 + 落盘 db/schema.sql（DDL 与库结构同源，便于复查）；
  2. 从 data/processed/brfss_clean.parquet 流式读取（每批 5 万行），
     executemany 批量写入 fact_brfss（避免一次性载入内存）；
  3. 主键 seq_key + 5 个业务索引；
  4. 由 fact_brfss 在库内聚合生成 dim_* 与 agg_* 表（保证文档与库一致）；
  5. 执行若干校验 SQL：行数一致性、每慢病患病率、共病率、索引检查。

用法：python pipeline/06_build_db.py
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timezone

import pyarrow.parquet as pq
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROCESSED = os.path.join(ROOT, "data", "processed", "brfss_clean.parquet")
DB_DIR = os.path.join(ROOT, "db")
DB_PATH = os.path.join(DB_DIR, "chronic_risk.db")
SCHEMA_PATH = os.path.join(DB_DIR, "schema.sql")
DICT_CSV = os.path.join(ROOT, "data", "raw", "dictionary", "dictionary.csv")
METRICS_DIR = os.path.join(ROOT, "artifacts", "metrics")
LOG_PATH = os.path.join(METRICS_DIR, "pipeline_log.json")
BATCH = 50000

# fact_brfss 列顺序（与清洗脚本输出顺序、后端契约完全一致）
FACT_COLUMNS = [
    "seq_key", "year", "state_fips", "month", "sex", "age", "age_grp",
    "race", "hispanic", "educa", "income_grp", "employ", "marital", "veteran",
    "bmi", "obese", "smoker3", "phys_activity", "heavy_drink", "genhlth",
    "poor_health", "menthlth", "physhlth", "checkup", "medcost", "persdoc",
    "diffwalk", "has_diabetes", "has_mi", "has_chd", "has_stroke", "has_copd",
    "has_asthma", "has_kidney", "has_depression", "chronic_count", "multimorbidity",
]

# 慢病字典：列名 / 中文名 / 英文名 / 源变量（跨年调和后）
CHRONIC_DICT = [
    ("has_diabetes", "糖尿病", "Diabetes", "DIABETE4"),
    ("has_mi", "心肌梗死", "Myocardial infarction", "CVDINFR4"),
    ("has_chd", "冠心病", "Coronary heart disease", "CVDCRHD4"),
    ("has_stroke", "卒中", "Stroke", "CVDSTRK3"),
    ("has_copd", "慢性阻塞性肺疾病", "COPD", "CHCCOPD2/CHCCOPD3"),
    ("has_asthma", "哮喘", "Asthma", "ASTHMA3"),
    ("has_kidney", "慢性肾病", "Kidney disease", "CHCKDNY2"),
    ("has_depression", "抑郁障碍", "Depressive disorder", "ADDEPEV3"),
    ("multimorbidity", "共病（慢病数≥2）", "Multimorbidity", "chronic_count>=2"),
]

# 州 FIPS → (USPS 缩写, 人口普查分区)
STATE_META = {
    1: ("AL", "South"), 2: ("AK", "West"), 4: ("AZ", "West"), 5: ("AR", "South"),
    6: ("CA", "West"), 8: ("CO", "West"), 9: ("CT", "Northeast"), 10: ("DE", "South"),
    11: ("DC", "South"), 12: ("FL", "South"), 13: ("GA", "South"), 15: ("HI", "West"),
    16: ("ID", "West"), 17: ("IL", "Midwest"), 18: ("IN", "Midwest"), 19: ("IA", "Midwest"),
    20: ("KS", "Midwest"), 21: ("KY", "South"), 22: ("LA", "South"), 23: ("ME", "Northeast"),
    24: ("MD", "South"), 25: ("MA", "Northeast"), 26: ("MI", "Midwest"), 27: ("MN", "Midwest"),
    28: ("MS", "South"), 29: ("MO", "Midwest"), 30: ("MT", "West"), 31: ("NE", "Midwest"),
    32: ("NV", "West"), 33: ("NH", "Northeast"), 34: ("NJ", "Northeast"), 35: ("NM", "West"),
    36: ("NY", "Northeast"), 37: ("NC", "South"), 38: ("ND", "Midwest"), 39: ("OH", "Midwest"),
    40: ("OK", "South"), 41: ("OR", "West"), 42: ("PA", "Northeast"), 44: ("RI", "Northeast"),
    45: ("SC", "South"), 46: ("SD", "Midwest"), 47: ("TN", "South"), 48: ("TX", "South"),
    49: ("UT", "West"), 50: ("VT", "Northeast"), 51: ("VA", "South"), 53: ("WA", "West"),
    54: ("WV", "South"), 55: ("WI", "Midwest"), 56: ("WY", "West"),
    66: ("GU", "Territory"), 72: ("PR", "Territory"), 78: ("VI", "Territory"),
}

# 危险因素定义：(risk_factor, 中文名, SQL 分子, SQL 分母, level_label)
RISK_FACTORS = [
    ("obese", "肥胖(BMI≥30)", "SUM(obese = 1)", "COUNT(obese)", "是"),
    ("current_smoker", "现吸烟(每日或部分日)", "SUM(smoker3 IN (1,2))", "COUNT(smoker3)", "是"),
    ("no_phys_activity", "无闲暇体力活动", "SUM(phys_activity = 0)", "COUNT(phys_activity)", "无"),
    ("heavy_drink", "暴饮(binge)2022+", "SUM(heavy_drink = 1)", "COUNT(heavy_drink)", "是"),
    ("cost_barrier", "因费用未就医", "SUM(medcost = 1)", "COUNT(medcost)", "是"),
    ("no_personal_doctor", "无固定医生", "SUM(persdoc = 3)", "COUNT(persdoc)", "是"),
    ("fair_poor_health", "自评健康差/一般", "SUM(poor_health = 1)", "COUNT(poor_health)", "是"),
    ("diff_walk", "行走/爬楼困难", "SUM(diffwalk = 1)", "COUNT(diffwalk)", "是"),
    ("checkup_over_1y", "超过1年未体检", "SUM(checkup IN (2,3,4,8))", "COUNT(checkup)", "是"),
]

SCHEMA_SQL = """-- 慢性病患者健康风险预测与干预 · SQLite 分析库结构
-- 由 pipeline/06_build_db.py 自动生成/覆盖，请勿手工修改

DROP TABLE IF EXISTS fact_brfss;
DROP TABLE IF EXISTS dim_year;
DROP TABLE IF EXISTS dim_state;
DROP TABLE IF EXISTS dim_age_group;
DROP TABLE IF EXISTS dim_income_group;
DROP TABLE IF EXISTS dim_education;
DROP TABLE IF EXISTS dim_chronic;
DROP TABLE IF EXISTS agg_prevalence_year;
DROP TABLE IF EXISTS agg_prevalence_state;
DROP TABLE IF EXISTS agg_risk_factor;
DROP TABLE IF EXISTS agg_risk_stratum;
DROP TABLE IF EXISTS model_metrics;
DROP TABLE IF EXISTS audit_pipeline;

-- 维度：年份
CREATE TABLE dim_year (
    year        INTEGER PRIMARY KEY,
    year_label  TEXT,
    n_records   INTEGER
);

-- 维度：州（FIPS）
CREATE TABLE dim_state (
    state_fips  INTEGER PRIMARY KEY,
    state_name  TEXT,
    state_abbr  TEXT,
    region      TEXT,
    n_records   INTEGER
);

-- 维度：年龄组（_AGEG5YR 1-13）
CREATE TABLE dim_age_group (
    age_grp     INTEGER PRIMARY KEY,
    age_label   TEXT
);

-- 维度：收入组（_INCOMG 5 档，_INCOMG1 已折叠）
CREATE TABLE dim_income_group (
    income_grp   INTEGER PRIMARY KEY,
    income_label TEXT
);

-- 维度：教育（EDUCA 1-6）
CREATE TABLE dim_education (
    educa       INTEGER PRIMARY KEY,
    educa_label TEXT
);

-- 维度：慢病字典
CREATE TABLE dim_chronic (
    disease_code   TEXT PRIMARY KEY,
    disease_name_cn TEXT,
    disease_name_en TEXT,
    source_var     TEXT,
    is_primary_label INTEGER
);

-- 事实表：清洗后 BRFSS 明细（主键 seq_key = 年份_STSTR_SEQNO）
CREATE TABLE fact_brfss (
    seq_key        TEXT PRIMARY KEY,   -- 年份_STSTR(层)_SEQNO，见数据字典“主键”节
    year           INTEGER NOT NULL,
    state_fips     INTEGER,
    month          INTEGER,
    sex            INTEGER,
    age            INTEGER,
    age_grp        INTEGER,
    race           INTEGER,
    hispanic       INTEGER,   -- 二值：1=西班牙裔 0=否（_HISPANC 1/2 归一化）
    educa          INTEGER,
    income_grp     INTEGER,
    employ         INTEGER,
    marital        INTEGER,
    veteran        INTEGER,   -- 二值：1=退伍军人 0=否（VETERAN3 1/2 归一化）
    bmi            REAL,   -- _BMI5/100，<10 或 >70 已置 NULL
    obese          INTEGER,
    smoker3        INTEGER,
    phys_activity  INTEGER,   -- 二值：1=有闲暇体力活动 0=无（_TOTINDA 1/2 归一化）
    heavy_drink    INTEGER,   -- 二值：1=暴饮 0=否（_RFBING6 2/1 归一化，仅 2022-2023 有值）
    genhlth        INTEGER,   -- 有序分类 1 优 … 5 差（保持原码）
    poor_health    INTEGER,   -- 二值：1=自评一般/差 0=好及以上（_RFHLTH 2/1 归一化）
    menthlth       INTEGER,
    physhlth       INTEGER,
    checkup        INTEGER,
    medcost        INTEGER,   -- 二值：1=因费用未就医 0=否（MEDCOST 1/2 归一化）
    persdoc        INTEGER,   -- 有序分类 1 只有一位 / 2 多于一位 / 3 没有
    diffwalk       INTEGER,   -- 二值：1=行走/爬楼困难 0=否（DIFFWALK 1/2 归一化）
    has_diabetes   INTEGER,
    has_mi         INTEGER,
    has_chd        INTEGER,
    has_stroke     INTEGER,
    has_copd       INTEGER,
    has_asthma     INTEGER,
    has_kidney     INTEGER,
    has_depression INTEGER,
    chronic_count  INTEGER,
    multimorbidity INTEGER
);

CREATE INDEX idx_fact_year           ON fact_brfss(year);
CREATE INDEX idx_fact_state          ON fact_brfss(state_fips);
CREATE INDEX idx_fact_diabetes       ON fact_brfss(has_diabetes);
CREATE INDEX idx_fact_multimorbidity ON fact_brfss(multimorbidity);
CREATE INDEX idx_fact_age_grp        ON fact_brfss(age_grp);

-- 聚合：按年 × 慢病的患病率
CREATE TABLE agg_prevalence_year (
    year            INTEGER NOT NULL,
    disease_code    TEXT    NOT NULL,
    disease_name_cn TEXT,
    n_valid         INTEGER,
    n_positive      INTEGER,
    prevalence      REAL,
    PRIMARY KEY (year, disease_code)
);

-- 聚合：按年 × 州 × 慢病
CREATE TABLE agg_prevalence_state (
    year            INTEGER NOT NULL,
    state_fips      INTEGER NOT NULL,
    disease_code    TEXT    NOT NULL,
    n_valid         INTEGER,
    n_positive      INTEGER,
    prevalence      REAL,
    PRIMARY KEY (year, state_fips, disease_code)
);

-- 聚合：危险因素暴露率（按年）
CREATE TABLE agg_risk_factor (
    year          INTEGER NOT NULL,
    risk_factor   TEXT    NOT NULL,
    risk_label_cn TEXT,
    level_label   TEXT,
    n_valid       INTEGER,
    n_positive    INTEGER,
    exposure_rate REAL,
    PRIMARY KEY (year, risk_factor)
);

-- 聚合：风险分层（多个维度共用一张表）
CREATE TABLE agg_risk_stratum (
    dimension         TEXT NOT NULL,
    stratum_code      INTEGER NOT NULL,
    stratum_label     TEXT,
    n                 INTEGER,
    n_multimorbidity  INTEGER,
    multimorbidity_rate REAL,
    PRIMARY KEY (dimension, stratum_code)
);

-- 模型指标（由 05_train.py 写入；后端 SELECT * 直出）
CREATE TABLE model_metrics (
    model_name TEXT NOT NULL,
    metric     TEXT NOT NULL,
    value      REAL,
    PRIMARY KEY (model_name, metric)
);

-- 流水线审计
CREATE TABLE audit_pipeline (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT,
    step        TEXT,
    started_at  TEXT,
    finished_at TEXT,
    elapsed_sec REAL,
    rows_in     INTEGER,
    rows_out    INTEGER,
    detail      TEXT
);
"""


def log(msg: str) -> None:
    print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), msg), flush=True)


def load_dict_labels():
    """从 CDC 字典 csv 读取取值标签：返回 {变量: {code(str): label}}。"""
    import csv
    labels = {}
    if not os.path.exists(DICT_CSV):
        return labels
    with open(DICT_CSV, "r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            var = row.get("variable")
            vl = row.get("value_labels")
            if not var or not vl:
                continue
            if var in labels:
                continue
            try:
                items = json.loads(vl)
            except json.JSONDecodeError:
                continue
            labels[var] = {str(it.get("code")): it.get("label") for it in items}
    return labels


def create_schema(conn: sqlite3.Connection, run_id: str, t0: str) -> None:
    conn.executescript(SCHEMA_SQL)
    os.makedirs(DB_DIR, exist_ok=True)
    with open(SCHEMA_PATH, "w", encoding="utf-8") as f:
        f.write(SCHEMA_SQL)
    log("已建表并写出 %s" % SCHEMA_PATH)


def load_facts(conn: sqlite3.Connection) -> int:
    """流式分批导入 fact_brfss（每批 5 万行）。"""
    pf = pq.ParquetFile(PROCESSED)
    total = pf.metadata.num_rows
    log("待导入 %d 行，共 %d 个 row group，批大小 %d" % (total, pf.num_row_groups, BATCH))

    placeholders = ",".join(["?"] * len(FACT_COLUMNS))
    sql = "INSERT INTO fact_brfss (%s) VALUES (%s)" % (",".join(FACT_COLUMNS), placeholders)

    n = 0
    t_start = time.time()
    for batch in pf.iter_batches(batch_size=BATCH):
        df = batch.to_pandas()
        missing = [c for c in FACT_COLUMNS if c not in df.columns]
        if missing:
            raise RuntimeError("清洗结果缺少列：%s" % missing)
        df = df[FACT_COLUMNS]
        rows = list(df.itertuples(index=False, name=None))
        conn.executemany(sql, rows)
        n += len(rows)
        if (n // BATCH) % 5 == 0:
            log("  已导入 %d / %d 行（%.1fs）" % (n, total, time.time() - t_start))
    conn.commit()
    log("fact_brfss 导入完成：%d 行，耗时 %.1fs" % (n, time.time() - t_start))
    return n


def build_dims(conn: sqlite3.Connection) -> None:
    labels = load_dict_labels()
    cur = conn.cursor()

    # dim_year
    cur.execute("""INSERT INTO dim_year(year, year_label, n_records)
                   SELECT year, CAST(year AS TEXT) || ' 年', COUNT(*) FROM fact_brfss GROUP BY year""")

    # dim_state：州名取自 CDC 字典 _STATE 的取值标签
    state_labels = labels.get("_STATE", {})
    cur.execute("SELECT DISTINCT state_fips FROM fact_brfss WHERE state_fips IS NOT NULL")
    fips_present = sorted(r[0] for r in cur.fetchall())
    meta_rows = []
    for fips in fips_present:
        abbr, region = STATE_META.get(fips, (None, None))
        name = state_labels.get(str(fips), "Unknown(%d)" % fips)
        meta_rows.append((fips, name, abbr, region))
    cur.executemany("INSERT INTO dim_state(state_fips, state_name, state_abbr, region) VALUES (?,?,?,?)",
                    meta_rows)
    cur.execute("""UPDATE dim_state SET n_records =
                   (SELECT COUNT(*) FROM fact_brfss f WHERE f.state_fips = dim_state.state_fips)""")

    # dim_age_group（_AGEG5YR 1-13）
    age_labels = labels.get("_AGEG5YR", {})
    cur.executemany("INSERT INTO dim_age_group(age_grp, age_label) VALUES (?,?)",
                    [(i, age_labels.get(str(i), "")) for i in range(1, 14)])

    # dim_income_group（_INCOMG 5 档）
    inc_labels = labels.get("_INCOMG", {})
    cur.executemany("INSERT INTO dim_income_group(income_grp, income_label) VALUES (?,?)",
                    [(i, inc_labels.get(str(i), "")) for i in range(1, 6)])

    # dim_education（EDUCA 1-6）
    edu_labels = labels.get("EDUCA", {})
    cur.executemany("INSERT INTO dim_education(educa, educa_label) VALUES (?,?)",
                    [(i, edu_labels.get(str(i), "")) for i in range(1, 7)])

    # dim_chronic
    cur.executemany("""INSERT INTO dim_chronic(disease_code, disease_name_cn, disease_name_en,
                                               source_var, is_primary_label)
                       VALUES (?,?,?,?,?)""",
                    [(c, cn, en, src, 1 if c == "multimorbidity" else 0)
                     for c, cn, en, src in CHRONIC_DICT])
    conn.commit()
    log("dim_* 维表构建完成（州 %d 个）" % len(meta_rows))


def build_aggs(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    diseases = [(c, cn) for c, cn, _en, _s in CHRONIC_DICT if c != "multimorbidity"]
    diseases.append(("multimorbidity", "共病（慢病数≥2）"))

    # agg_prevalence_year
    for code, name_cn in diseases:
        cur.execute("""
            INSERT INTO agg_prevalence_year(year, disease_code, disease_name_cn, n_valid, n_positive, prevalence)
            SELECT year, ?, ?, COUNT({c}), SUM(CASE WHEN {c}=1 THEN 1 ELSE 0 END),
                   ROUND(1.0*SUM(CASE WHEN {c}=1 THEN 1 ELSE 0 END)/COUNT({c}), 6)
            FROM fact_brfss GROUP BY year""".format(c=code), (code, name_cn))

    # agg_prevalence_state
    for code, _nc in diseases:
        cur.execute("""
            INSERT INTO agg_prevalence_state(year, state_fips, disease_code, n_valid, n_positive, prevalence)
            SELECT year, state_fips, ?, COUNT({c}), SUM(CASE WHEN {c}=1 THEN 1 ELSE 0 END),
                   ROUND(1.0*SUM(CASE WHEN {c}=1 THEN 1 ELSE 0 END)/COUNT({c}), 6)
            FROM fact_brfss WHERE state_fips IS NOT NULL GROUP BY year, state_fips""".format(c=code), (code,))

    # agg_risk_factor
    for rf, label_cn, num, den, level_label in RISK_FACTORS:
        cur.execute("""
            INSERT INTO agg_risk_factor(year, risk_factor, risk_label_cn, level_label,
                                        n_valid, n_positive, exposure_rate)
            SELECT year, ?, ?, ?, {den}, {num}, ROUND(1.0*{num}/{den}, 6)
            FROM fact_brfss GROUP BY year""".format(num=num, den=den), (rf, label_cn, level_label))

    # agg_risk_stratum
    strata_sql = [
        ("chronic_count", """SELECT chronic_count AS code, CAST(chronic_count AS TEXT) AS lab,
                                    COUNT(*) AS n, SUM(multimorbidity) AS pos
                             FROM fact_brfss GROUP BY chronic_count"""),
        ("age_grp", """SELECT f.age_grp AS code,
                              COALESCE((SELECT age_label FROM dim_age_group d
                                        WHERE d.age_grp = f.age_grp), CAST(f.age_grp AS TEXT)) AS lab,
                              COUNT(*) AS n, SUM(f.multimorbidity) AS pos
                       FROM fact_brfss f WHERE f.age_grp IS NOT NULL GROUP BY f.age_grp"""),
        ("sex", """SELECT sex AS code,
                          CASE WHEN sex=1 THEN 'Male' WHEN sex=2 THEN 'Female' ELSE 'Unknown' END AS lab,
                          COUNT(*) AS n, SUM(multimorbidity) AS pos
                   FROM fact_brfss WHERE sex IS NOT NULL GROUP BY sex"""),
        ("smoker3", """SELECT smoker3 AS code,
                              CASE smoker3 WHEN 1 THEN 'Everyday smoker' WHEN 2 THEN 'Someday smoker'
                                           WHEN 3 THEN 'Former smoker' WHEN 4 THEN 'Never smoked'
                                           ELSE 'Unknown' END AS lab,
                              COUNT(*) AS n, SUM(multimorbidity) AS pos
                       FROM fact_brfss WHERE smoker3 IS NOT NULL GROUP BY smoker3"""),
        ("bmi_class", """SELECT CASE WHEN bmi<18.5 THEN 1 WHEN bmi<25 THEN 2 WHEN bmi<30 THEN 3 ELSE 4 END AS code,
                                   CASE WHEN bmi<18.5 THEN 'Underweight(<18.5)' WHEN bmi<25 THEN 'Normal(18.5-25)'
                                        WHEN bmi<30 THEN 'Overweight(25-30)' ELSE 'Obese(>=30)' END AS lab,
                                   COUNT(*) AS n, SUM(multimorbidity) AS pos
                            FROM fact_brfss WHERE bmi IS NOT NULL GROUP BY 1"""),
    ]
    for dim, sql in strata_sql:
        cur.execute("""
            INSERT INTO agg_risk_stratum(dimension, stratum_code, stratum_label, n,
                                         n_multimorbidity, multimorbidity_rate)
            SELECT ?, code, lab, n, pos, ROUND(1.0*pos/n, 6) FROM (%s)""" % sql, (dim,))
    conn.commit()
    log("agg_* 聚合表构建完成")


def verify(conn: sqlite3.Connection, n_parquet: int) -> dict:
    """执行校验 SQL：行数一致性、患病率、共病率、索引。"""
    cur = conn.cursor()
    out = {}
    cur.execute("SELECT COUNT(*) FROM fact_brfss")
    n_fact = cur.fetchone()[0]
    out["n_fact"] = n_fact
    out["n_parquet"] = n_parquet
    out["count_match"] = (n_fact == n_parquet)

    cur.execute("SELECT year, COUNT(*) FROM fact_brfss GROUP BY year ORDER BY year")
    out["rows_by_year"] = {str(y): int(c) for y, c in cur.fetchall()}

    cur.execute("""SELECT COUNT(*) FROM (SELECT seq_key FROM fact_brfss GROUP BY seq_key HAVING COUNT(*)>1)""")
    out["duplicate_seq_key"] = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM fact_brfss WHERE seq_key IS NULL OR year IS NULL")
    out["null_pk_rows"] = cur.fetchone()[0]

    cur.execute("""SELECT disease_code, n_valid, n_positive, prevalence FROM agg_prevalence_year
                   WHERE year=2023 AND disease_code IN
                   ('has_diabetes','has_mi','has_chd','has_stroke','has_copd','has_asthma',
                    'has_kidney','has_depression','multimorbidity')""")
    out["prevalence_2023"] = {r[0]: {"n_valid": r[1], "n_positive": r[2], "prevalence": r[3]}
                              for r in cur.fetchall()}

    cur.execute("""SELECT disease_code, ROUND(AVG(prevalence),6) FROM agg_prevalence_year
                   GROUP BY disease_code""")
    out["prevalence_avg_2019_2023"] = {r[0]: r[1] for r in cur.fetchall()}

    cur.execute("""SELECT y.year, ROUND(1.0*SUM(f.multimorbidity)/COUNT(*),6)
                   FROM fact_brfss f JOIN dim_year y ON y.year = f.year
                   GROUP BY y.year ORDER BY y.year""")
    out["multimorbidity_by_year"] = {str(r[0]): r[1] for r in cur.fetchall()}

    cur.execute("""SELECT s.state_name, COUNT(*) n, ROUND(1.0*SUM(f.multimorbidity)/COUNT(*),4) rate
                   FROM fact_brfss f JOIN dim_state s ON s.state_fips=f.state_fips
                   GROUP BY s.state_fips ORDER BY rate DESC LIMIT 5""")
    out["top5_state_multimorbidity"] = [{"state": r[0], "n": r[1], "rate": r[2]} for r in cur.fetchall()]

    # 二值字段分布（验证归一化：只有 0/1/NULL 三种取值）
    binary_cols = ["phys_activity", "heavy_drink", "poor_health", "obese", "multimorbidity",
                   "medcost", "diffwalk", "veteran", "hispanic",
                   "has_diabetes", "has_mi", "has_chd", "has_stroke", "has_copd",
                   "has_asthma", "has_kidney", "has_depression"]
    out["binary_dist"] = {}
    for c in binary_cols:
        cur.execute("SELECT SUM({c}=0), SUM({c}=1), SUM({c} IS NULL) FROM fact_brfss".format(c=c))
        zero, one, nul = cur.fetchone()
        out["binary_dist"][c] = {"zero": int(zero or 0), "one": int(one or 0), "null": int(nul or 0)}
    bd = out["binary_dist"]
    out["rates"] = {
        "heavy_drink_rate": round(bd["heavy_drink"]["one"] / max(1, bd["heavy_drink"]["one"] + bd["heavy_drink"]["zero"]), 6),
        "no_phys_activity_rate": round(bd["phys_activity"]["zero"] / max(1, bd["phys_activity"]["zero"] + bd["phys_activity"]["one"]), 6),
        "poor_health_rate": round(bd["poor_health"]["one"] / max(1, bd["poor_health"]["one"] + bd["poor_health"]["zero"]), 6),
        "obese_rate": round(bd["obese"]["one"] / max(1, bd["obese"]["one"] + bd["obese"]["zero"]), 6),
    }

    cur.execute("SELECT COUNT(*) FROM dim_state")
    out["n_states"] = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM agg_prevalence_year")
    out["n_agg_prevalence_year"] = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM agg_prevalence_state")
    out["n_agg_prevalence_state"] = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM agg_risk_factor")
    out["n_agg_risk_factor"] = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM agg_risk_stratum")
    out["n_agg_risk_stratum"] = cur.fetchone()[0]
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    out["tables"] = [r[0] for r in cur.fetchall()]
    cur.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%' ORDER BY name")
    out["indexes"] = [r[0] for r in cur.fetchall()]
    return out


def mirror_pipeline_log(conn: sqlite3.Connection, run_id: str) -> int:
    """把 artifacts/metrics/pipeline_log.json 中各步骤记录镜像进 audit_pipeline。

    这样数据质量与行数变化在库内即可追溯，无需外部文件即可核对 01/02 步骤。
    """
    if not os.path.exists(LOG_PATH):
        return 0
    try:
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError:
        return 0
    keep = ("label", "rows_in_by_year", "rows_out_by_year", "drop_rules", "value_rules",
            "output_file", "output_bytes", "seq_key_distinct", "db_bytes", "verification",
            "binary_dist", "rates", "engine")
    n = 0
    for s in data.get("steps", []):
        if s.get("step") == "06_build_db":       # 本步骤记录由 main() 单独写入
            continue
        detail = {k: s[k] for k in keep if k in s}
        conn.execute("""INSERT INTO audit_pipeline(run_id, step, started_at, finished_at, elapsed_sec,
                                                   rows_in, rows_out, detail)
                        VALUES (?,?,?,?,?,?,?,?)""",
                     (run_id, s.get("step"), s.get("started_at"), s.get("finished_at"),
                      s.get("elapsed_sec"), s.get("rows_in"), s.get("rows_out"),
                      json.dumps(detail, ensure_ascii=False)))
        n += 1
    return n


def append_pipeline_log(step: dict) -> None:
    os.makedirs(METRICS_DIR, exist_ok=True)
    data = {"steps": []}
    if os.path.exists(LOG_PATH):
        try:
            with open(LOG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            data.setdefault("steps", [])
        except json.JSONDecodeError:
            data = {"steps": []}
    data["generated_at"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    data["steps"] = [s for s in data["steps"] if s.get("step") != step["step"]] + [step]
    with open(LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main() -> int:
    t_start = time.time()
    run_id = uuid.uuid4().hex[:12]
    if not os.path.exists(PROCESSED):
        log("缺少 %s，请先运行 02_clean_spark.py" % PROCESSED)
        return 1
    os.makedirs(DB_DIR, exist_ok=True)
    if os.path.exists(DB_PATH):
        # 库可能正被 API 服务只读打开（Windows 下占用则无法删除），退避重试
        for attempt in range(1, 6):
            try:
                os.remove(DB_PATH)
                log("已删除旧的 %s" % DB_PATH)
                break
            except PermissionError:
                log("库文件被占用（可能 API 服务正在读取），第 %d/5 次重试…" % attempt)
                time.sleep(2)
        else:
            raise SystemExit("无法删除被占用的 %s：请先停止占用该库的服务（如 uvicorn api.main）后重跑" % DB_PATH)

    n_parquet = pq.ParquetFile(PROCESSED).metadata.num_rows
    started_at = datetime.now().astimezone().isoformat(timespec="seconds")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode = MEMORY")
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute("PRAGMA cache_size = -200000")   # 约 200MB 页缓存
    conn.execute("PRAGMA temp_store = MEMORY")

    # numpy 标量 → 原生类型（sqlite3 只接受 Python 原生类型）
    sqlite3.register_adapter(np.int64, int)
    sqlite3.register_adapter(np.int32, int)
    sqlite3.register_adapter(np.float64, float)
    sqlite3.register_adapter(np.float32, float)
    sqlite3.register_adapter(np.bool_, int)

    create_schema(conn, run_id, started_at)

    t_load = time.time()
    n_fact = load_facts(conn)
    load_sec = round(time.time() - t_load, 1)

    t_idx = time.time()
    conn.execute("ANALYZE")
    conn.commit()
    log("索引随建表 DDL 创建、插入期间增量维护；ANALYZE 完成（%.1fs）" % (time.time() - t_idx))

    t_agg = time.time()
    build_dims(conn)
    build_aggs(conn)
    agg_sec = round(time.time() - t_agg, 1)

    res = verify(conn, n_parquet)

    conn.execute("""INSERT INTO audit_pipeline(run_id, step, started_at, finished_at, elapsed_sec,
                                               rows_in, rows_out, detail)
                    VALUES (?,?,?,?,?,?,?,?)""",
                 (run_id, "06_build_db", started_at,
                  datetime.now().astimezone().isoformat(timespec="seconds"),
                  round(time.time() - t_start, 1), n_parquet, n_fact,
                  json.dumps({"load_sec": load_sec, "agg_sec": agg_sec,
                              "batch_size": BATCH, "tables": res["tables"]}, ensure_ascii=False)))
    # 镜像 01/02 等上游步骤的审计记录
    n_mirror = mirror_pipeline_log(conn, run_id)
    log("已镜像上游步骤审计记录 %d 条" % n_mirror)

    # 追加一条口径修订审计记录（二值字段归一化）
    conn.execute("""INSERT INTO audit_pipeline(run_id, step, started_at, finished_at, elapsed_sec,
                                               rows_in, rows_out, detail)
                    VALUES (?,?,?,?,?,?,?,?)""",
                 (run_id, "binary_normalization", started_at,
                  datetime.now().astimezone().isoformat(timespec="seconds"), 0.0, n_fact, n_fact,
                  json.dumps({
                      "rev": "契约修订2",
                      "rule": "二值字段一律 0/1，1 = 字段名所描述的状态成立",
                      "changes": {
                          "phys_activity": "_TOTINDA 1(有运动)→1, 2(无)→0, 9→NULL",
                          "heavy_drink": "_RFBING6 2(是/暴饮)→1, 1(否)→0, 9→NULL",
                          "poor_health": "_RFHLTH 2(一般/差)→1, 1(好及以上)→0, 9→NULL",
                          "hispanic": "_HISPANC 1(是)→1, 2(否)→0, 9→NULL",
                          "veteran": "VETERAN3 1(是)→1, 2(否)→0, 7/9→NULL",
                          "medcost": "MEDCOST/MEDCOST1 1(是)→1, 2(否)→0, 7/9→NULL",
                          "diffwalk": "DIFFWALK 1(是)→1, 2(否)→0, 7/9→NULL",
                      },
                      "unchanged": "has_* / obese / multimorbidity 原已为 0/1；smoker3(1-4)/genhlth(1-5)/checkup(1,2,3,4,8)/educa(1-6)/income_grp(1-5)/persdoc(1-3)/sex(1,2) 为有序或名义分类，保持原码",
                      "rows": n_fact,
                  }, ensure_ascii=False)))
    conn.commit()
    db_bytes = os.path.getsize(DB_PATH)
    # 保持默认回滚日志模式：单文件库，只读连接（API 层）无需额外 -wal/-shm 文件
    conn.close()

    elapsed = round(time.time() - t_start, 1)
    log("库文件 %s（%.1f MB）" % (DB_PATH, db_bytes / 1024 / 1024))
    log("校验：fact_brfss=%d / parquet=%d / 一致=%s / 重复主键=%d"
        % (res["n_fact"], res["n_parquet"], res["count_match"], res["duplicate_seq_key"]))
    log("各年行数：%s" % res["rows_by_year"])
    log("2023 年各类慢病患病率：")
    for k, v in res["prevalence_2023"].items():
        log("    %-16s %8d / %8d = %.4f" % (k, v["n_positive"], v["n_valid"], v["prevalence"]))
    log("共病率（按年）：%s" % res["multimorbidity_by_year"])
    log("二值字段分布（0/1/NULL）：%s" % json.dumps(
        {k: res["binary_dist"][k] for k in ("phys_activity", "heavy_drink", "poor_health")},
        ensure_ascii=False))
    log("归一化后暴露率：无运动 %.4f / 暴饮 %.4f / 自评差 %.4f / 肥胖 %.4f"
        % (res["rates"]["no_phys_activity_rate"], res["rates"]["heavy_drink_rate"],
           res["rates"]["poor_health_rate"], res["rates"]["obese_rate"]))
    log("指数：%s" % res["indexes"])

    append_pipeline_log({
        "step": "06_build_db",
        "label": "SQLite 建库与聚合",
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "elapsed_sec": elapsed,
        "load_sec": load_sec,
        "agg_sec": agg_sec,
        "batch_size": BATCH,
        "rows_in": n_parquet,
        "rows_out": n_fact,
        "db_path": os.path.relpath(DB_PATH, ROOT).replace("\\", "/"),
        "db_bytes": db_bytes,
        "schema_path": os.path.relpath(SCHEMA_PATH, ROOT).replace("\\", "/"),
        "verification": res,
    })
    log("耗时 %.1f 秒；审计已写入 %s" % (elapsed, LOG_PATH))
    return 0 if res["count_match"] and res["duplicate_seq_key"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
