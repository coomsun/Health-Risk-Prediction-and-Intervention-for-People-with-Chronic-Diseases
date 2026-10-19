-- 慢性病患者健康风险预测与干预 · SQLite 分析库结构
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
