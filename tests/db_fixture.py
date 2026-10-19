"""测试用 SQLite 建库工具：按 _设计规格.md 第 4 节的结构产出库文件。

真实库由 pipeline/06_build_db.py 生成；这里只在临时目录里造同结构的
空库/样例库，用于后端接口的自动化测试，不参与交付数据。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable, Sequence

#: 与 pipeline 产出保持一致的建表语句（字段口径见规格第 2、4 节）
SCHEMA_SQL = """
CREATE TABLE fact_brfss (
    seq_key        TEXT PRIMARY KEY,
    year           INTEGER,
    state_fips     INTEGER,
    month          INTEGER,
    sex            INTEGER,
    age            INTEGER,
    age_grp        INTEGER,
    race           INTEGER,
    hispanic       INTEGER,
    educa          INTEGER,
    income_grp     INTEGER,
    employ         INTEGER,
    marital        INTEGER,
    veteran        INTEGER,
    bmi            REAL,
    obese          INTEGER,
    smoker3        INTEGER,
    phys_activity  INTEGER,
    heavy_drink    INTEGER,
    genhlth        INTEGER,
    poor_health    INTEGER,
    menthlth       INTEGER,
    physhlth       INTEGER,
    checkup        INTEGER,
    medcost        INTEGER,
    persdoc        INTEGER,
    diffwalk       INTEGER,
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

CREATE INDEX idx_fact_year ON fact_brfss(year);
CREATE INDEX idx_fact_state ON fact_brfss(state_fips);
CREATE INDEX idx_fact_diabetes ON fact_brfss(has_diabetes);
CREATE INDEX idx_fact_multimorbidity ON fact_brfss(multimorbidity);
CREATE INDEX idx_fact_age_grp ON fact_brfss(age_grp);

-- 维度表与聚合表结构对齐交付库（见 db/schema.sql），保证测试走真实列名
CREATE TABLE dim_year (year INTEGER PRIMARY KEY, year_label TEXT, n_records INTEGER);
CREATE TABLE dim_state (state_fips INTEGER PRIMARY KEY, state_name TEXT, state_abbr TEXT, region TEXT, n_records INTEGER);
CREATE TABLE dim_age_group (age_grp INTEGER PRIMARY KEY, age_label TEXT);
CREATE TABLE dim_income_group (income_grp INTEGER PRIMARY KEY, income_label TEXT);
CREATE TABLE dim_education (educa INTEGER PRIMARY KEY, educa_label TEXT);
CREATE TABLE dim_chronic (
    disease_code TEXT PRIMARY KEY, disease_name_cn TEXT, disease_name_en TEXT,
    source_var TEXT, is_primary_label INTEGER
);

CREATE TABLE agg_prevalence_year (
    year INTEGER, disease_code TEXT, disease_name_cn TEXT,
    n_valid INTEGER, n_positive INTEGER, prevalence REAL,
    PRIMARY KEY (year, disease_code)
);
CREATE TABLE agg_prevalence_state (
    year INTEGER, state_fips INTEGER, disease_code TEXT,
    n_valid INTEGER, n_positive INTEGER, prevalence REAL,
    PRIMARY KEY (year, state_fips, disease_code)
);
CREATE TABLE agg_risk_factor (
    year INTEGER, risk_factor TEXT, risk_label_cn TEXT, level_label TEXT,
    n_valid INTEGER, n_positive INTEGER, exposure_rate REAL,
    PRIMARY KEY (year, risk_factor)
);
CREATE TABLE agg_risk_stratum (
    dimension TEXT, stratum_code INTEGER, stratum_label TEXT,
    n INTEGER, n_multimorbidity INTEGER, multimorbidity_rate REAL,
    PRIMARY KEY (dimension, stratum_code)
);
CREATE TABLE model_metrics (model_name TEXT, metric TEXT, value REAL, PRIMARY KEY (model_name, metric));
CREATE TABLE audit_pipeline (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, step TEXT,
    started_at TEXT, finished_at TEXT, elapsed_sec REAL,
    rows_in INTEGER, rows_out INTEGER, detail TEXT
);
"""

#: fact_brfss 的列顺序（与 SCHEMA_SQL 一致，供批量插入使用）
FACT_COLUMNS: tuple[str, ...] = (
    "seq_key", "year", "state_fips", "month", "sex", "age", "age_grp", "race",
    "hispanic", "educa", "income_grp", "employ", "marital", "veteran", "bmi",
    "obese", "smoker3", "phys_activity", "heavy_drink", "genhlth", "poor_health",
    "menthlth", "physhlth", "checkup", "medcost", "persdoc", "diffwalk",
    "has_diabetes", "has_mi", "has_chd", "has_stroke", "has_copd", "has_asthma",
    "has_kidney", "has_depression", "chronic_count", "multimorbidity",
)

DISEASE_FIELDS: tuple[str, ...] = (
    "has_diabetes", "has_mi", "has_chd", "has_stroke",
    "has_copd", "has_asthma", "has_kidney", "has_depression",
)


def create_db(path: Path, rows: Iterable[dict[str, Any]] = ()) -> Path:
    """建库并（可选）写入明细行；自动补齐 chronic_count / multimorbidity。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.execute("INSERT INTO dim_state VALUES (6, 'California', 'CA', 'West', NULL)")
        conn.execute("INSERT INTO dim_state VALUES (48, 'Texas', 'TX', 'South', NULL)")
        conn.execute("INSERT INTO dim_age_group VALUES (5, '40-44')")
        conn.executemany(
            "INSERT INTO dim_chronic (disease_code, disease_name_cn) VALUES (?, ?)",
            [(field, field) for field in DISEASE_FIELDS],
        )
        payload = []
        for row in rows:
            record = {column: None for column in FACT_COLUMNS}
            record.update({k: v for k, v in row.items() if k in record})
            counts = [record.get(field) for field in DISEASE_FIELDS]
            if all(value is None for value in counts):
                record["chronic_count"] = None
                record["multimorbidity"] = None
            else:
                chronic_count = sum(int(v) for v in counts if v is not None)
                record["chronic_count"] = chronic_count
                record["multimorbidity"] = 1 if chronic_count >= 2 else 0
            if record.get("obese") is None and record.get("bmi") is not None:
                record["obese"] = 1 if record["bmi"] >= 30 else 0
            payload.append(tuple(record[column] for column in FACT_COLUMNS))
        if payload:
            placeholders = ", ".join("?" for _ in FACT_COLUMNS)
            conn.executemany(
                f"INSERT INTO fact_brfss ({', '.join(FACT_COLUMNS)}) VALUES ({placeholders})",
                payload,
            )
        conn.commit()
    finally:
        conn.close()
    return path


def sample_rows() -> list[dict[str, Any]]:
    """确定性样例数据：2 个年份 × 2 个州 × 6 条记录，共 24 行。

    数据本身只是测试输入，接口的期望值在测试里由这些行现场统计得出，
    不存在"把统计结果写死"的问题。
    """
    rows: list[dict[str, Any]] = []
    for year in (2022, 2023):
        for state in (6, 48):
            for index in range(6):
                flags = {
                    "has_diabetes": 1 if index % 3 == 0 else 0,
                    "has_mi": 1 if index % 4 == 0 else 0,
                    "has_chd": 1 if index >= 4 else 0,
                    "has_stroke": 0,
                    "has_copd": 1 if index == 5 else 0,
                    "has_asthma": 1 if index % 2 == 0 else 0,
                    "has_kidney": 1 if index == 2 else 0,
                    "has_depression": 1 if index % 3 == 2 else 0,
                }
                rows.append(
                    {
                        "seq_key": f"{year}_{state}_{index}",
                        "year": year,
                        "state_fips": state,
                        "month": 1 + index,
                        "sex": 1 + index % 2,
                        "age": 30 + index * 5,
                        "age_grp": 1 + index % 13,
                        "race": 1,
                        "hispanic": 1,
                        "educa": 4,
                        "income_grp": 5,
                        "employ": 1,
                        "marital": 1,
                        "veteran": 2,
                        "bmi": 22.0 + index * 3.0,
                        "smoker3": 1 + index % 4,
                        # 统一 0/1 约定：phys_activity 1=有运动、0=无；heavy_drink 1=酗酒
                        "phys_activity": 1 if index % 2 == 0 else 0,
                        "heavy_drink": 1 if index % 3 == 1 else 0,
                        "genhlth": 1 + index % 5,
                        "poor_health": 1 + index % 3,
                        "menthlth": index * 3,
                        "physhlth": index * 2,
                        "checkup": 1 if index % 2 == 0 else 8,
                        "medcost": 1 if index == 1 else 2,
                        "persdoc": 1 + index % 3,
                        "diffwalk": 1 if index >= 5 else 2,
                        **flags,
                    }
                )
    return rows
