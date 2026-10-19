# -*- coding: utf-8 -*-
"""02_clean_spark.py —— PySpark(local) 清洗五年 BRFSS 数据

清洗口径（与 docs/设计规格.md 第 2 节一致）：
  1. 跨年调和：CHCCOPD2→CHCCOPD3、MEDCOST→MEDCOST1、_INCOMG→_INCOMG1、
     PERSDOC2→PERSDOC3、_RACE 缺失年份(2022) 用 _MRACE2 + _HISPANC 还原；
  2. 缺失码 → NULL（**逐变量**指定，因为 7 在 EMPLOY1/_MRACE1 中是合法取值）；
  3. BMI = _BMI5/100，<10 或 >70 视为异常 → NULL；
  4. 构造 8 个慢病标志位、chronic_count、multimorbidity(=chronic_count>=2)；
     所有二值字段统一为 0/1，且 **1 = 字段名所描述的状态成立**
     （phys_activity 1=有运动；heavy_drink 1=暴饮；poor_health 1=自评一般/差；
      hispanic 1=西班牙裔；veteran 1=退伍军人；medcost 1=因费用未就医；diffwalk 1=行走困难）；
  5. 8 个标志位全 NULL 的行 label_valid=0，剔除。

输出：data/processed/brfss_clean.parquet（单文件，便于 pandas/pyarrow 直接读取）
审计：artifacts/metrics/pipeline_log.json（每步行数、丢弃数、缺失率）

用法：python pipeline/02_clean_spark.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone

# ---- 环境变量必须在导入 pyspark 之前设置（否则 JVM 起不来）----
os.environ.setdefault("JAVA_HOME", r"D:\jdk17")
os.environ.setdefault("SPARK_HOME", r"D:\sparkhome")
_PY = r"D:\期末作业\.venv\Scripts\python.exe"
os.environ.setdefault("PYSPARK_PYTHON", _PY)
os.environ.setdefault("PYSPARK_DRIVER_PYTHON", _PY)

import pyarrow as pa            # noqa: E402
import pyarrow.parquet as pq    # noqa: E402
from pyspark.sql import SparkSession, functions as F  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(ROOT, "data", "raw")
PROCESSED_DIR = os.path.join(ROOT, "data", "processed")
OUT_FILE = os.path.join(PROCESSED_DIR, "brfss_clean.parquet")
METRICS_DIR = os.path.join(ROOT, "artifacts", "metrics")
LOG_PATH = os.path.join(METRICS_DIR, "pipeline_log.json")
YEARS = [2019, 2020, 2021, 2022, 2023]

# 8 个慢病标志位：(输出列名, 含义)
CHRONIC_FLAGS = [
    ("has_diabetes", "糖尿病"),
    ("has_mi", "心肌梗死"),
    ("has_chd", "冠心病"),
    ("has_stroke", "卒中"),
    ("has_copd", "慢阻肺"),
    ("has_asthma", "哮喘"),
    ("has_kidney", "慢性肾病"),
    ("has_depression", "抑郁"),
]


def log(msg: str) -> None:
    print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), msg), flush=True)


def arrow_schema_of(df):
    """把 Spark schema 映射为 Arrow schema（本项目输出仅 int/double/string 三类）。"""
    from pyspark.sql import types as T
    mapping = [(T.IntegerType, pa.int32()), (T.LongType, pa.int64()),
               (T.DoubleType, pa.float64()), (T.StringType, pa.string())]
    fields = []
    for f in df.schema.fields:
        for st, at in mapping:
            if isinstance(f.dataType, st):
                fields.append(pa.field(f.name, at))
                break
        else:
            raise TypeError("未支持的 Spark 类型：%s (%s)" % (f.dataType, f.name))
    return pa.schema(fields)


def write_parquet_via_arrow(df, out_file: str, batch_rows: int = 50000) -> int:
    """在各 Spark 分区内用 pyarrow 分批写 part 文件，再由 driver 合并为单个 parquet。

    说明：本机 Windows 环境缺少 winutils.exe，Spark 的 DataFrameWriter 会在
    FileOutputCommitter.setupJob → RawLocalFileSystem.mkdirs → chmod 处抛
    HADOOP_HOME 异常（实测本机 Spark 4.2 无法写出）。因此改由 Arrow 批量落盘：
    全程按 5 万行分批，不做 toPandas() 全量转换，内存占用恒定。
    """
    schema = arrow_schema_of(df)
    names = [f.name for f in schema]
    tmp = out_file + "_parts"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)

    def _to_table(rows):
        arrays = [pa.array([r[i] for r in rows], type=schema.field(i).type) for i in range(len(names))]
        return pa.Table.from_arrays(arrays, names=names)

    def _write_part(idx, it):
        path = os.path.join(tmp, "part-%03d.parquet" % idx)
        writer = pq.ParquetWriter(path, schema, compression="snappy")
        buf = []
        for row in it:
            buf.append(row)
            if len(buf) >= batch_rows:
                writer.write_table(_to_table(buf))
                buf = []
        if buf:
            writer.write_table(_to_table(buf))
        writer.close()
        yield path

    parts = sorted(df.rdd.mapPartitionsWithIndex(_write_part).collect())
    log("分区写出 %d 个 part 文件，开始合并" % len(parts))
    writer = pq.ParquetWriter(out_file, schema, compression="snappy")
    n = 0
    for p in parts:
        for b in pq.ParquetFile(p).iter_batches(batch_size=batch_rows):
            writer.write_batch(b)
            n += b.num_rows
    writer.close()
    shutil.rmtree(tmp, ignore_errors=True)
    return n


def has_cols(df, names) -> bool:
    s = set(df.columns)
    return all(n in s for n in names)


def pick(df, *candidates):
    """返回第一个存在的列名（跨年调和用）。"""
    s = set(df.columns)
    for c in candidates:
        if c in s:
            return c
    return None


def build_year_frame(spark: SparkSession, year: int):
    """读取单年 parquet，产出跨年统一列名的 DataFrame（只读需要的列，减少 IO）。"""
    path = os.path.join(RAW_DIR, "LLCP%d.parquet" % year)
    src = spark.read.parquet(path)

    copd = pick(src, "CHCCOPD3", "CHCCOPD2")
    medcost = pick(src, "MEDCOST1", "MEDCOST")
    persdoc = pick(src, "PERSDOC3", "PERSDOC2")
    incomg = pick(src, "_INCOMG1", "_INCOMG")
    rfbing = pick(src, "_RFBING6")
    race_var = pick(src, "_RACE")
    mrace2 = pick(src, "_MRACE2")

    avail = set(src.columns)
    candidates = [
        "SEQNO", "_STSTR", "FMONTH", "_STATE", "_SEX", "_AGE80", "_AGEG5YR", "_HISPANC",
        "EDUCA", "EMPLOY1", "MARITAL", "VETERAN3",
        "DIABETE4", "CVDINFR4", "CVDCRHD4", "CVDSTRK3", "ASTHMA3", "CHCKDNY2",
        "ADDEPEV3", "GENHLTH", "_RFHLTH", "MENTHLTH", "PHYSHLTH", "CHECKUP1",
        "DIFFWALK", "_BMI5", "_SMOKER3", "_TOTINDA", copd, medcost, persdoc,
        incomg, rfbing, race_var, mrace2,
    ]
    # 只选本年度真实存在的列（各年变量集不同，避免 unresolved column）
    needed = [c for c in candidates if c and c in avail]

    df = src.select(*sorted(set(needed)))
    out = df.select(
        F.lit(year).cast("int").alias("year"),
        F.col("SEQNO").cast("int").alias("seqno"),
        F.col("_STSTR").cast("int").alias("ststr"),
        F.col("FMONTH").cast("int").alias("month"),
        F.col("_STATE").cast("int").alias("state_fips"),
        F.col("_SEX").cast("int").alias("sex"),
        F.col("_AGE80").cast("int").alias("age"),
        F.col("_AGEG5YR").cast("int").alias("age_grp"),
        F.col("_HISPANC").cast("int").alias("hispanic"),
        F.col("EDUCA").cast("int").alias("educa"),
        F.col("EMPLOY1").cast("int").alias("employ"),
        F.col("MARITAL").cast("int").alias("marital"),
        F.col("VETERAN3").cast("int").alias("veteran"),
        F.col("DIABETE4").cast("int").alias("diabete4"),
        F.col("CVDINFR4").cast("int").alias("cvdinfr4"),
        F.col("CVDCRHD4").cast("int").alias("cvdchd4"),
        F.col("CVDSTRK3").cast("int").alias("cvdstrk3"),
        F.col("ASTHMA3").cast("int").alias("asthma3"),
        F.col("CHCKDNY2").cast("int").alias("chckdny2"),
        F.col("ADDEPEV3").cast("int").alias("addep3"),
        F.col(copd).cast("int").alias("copd_raw"),
        F.col("GENHLTH").cast("int").alias("genhlth_raw"),
        F.col("_RFHLTH").cast("int").alias("rfhlth_raw"),
        F.col("MENTHLTH").cast("int").alias("menthlth_raw"),
        F.col("PHYSHLTH").cast("int").alias("physhlth_raw"),
        F.col("CHECKUP1").cast("int").alias("checkup_raw"),
        F.col("DIFFWALK").cast("int").alias("diffwalk_raw"),
        F.col("_BMI5").cast("int").alias("bmi5"),
        F.col("_SMOKER3").cast("int").alias("smoker3_raw"),
        F.col("_TOTINDA").cast("int").alias("totinda_raw"),
        F.col(medcost).cast("int").alias("medcost_raw"),
        F.col(persdoc).cast("int").alias("persdoc_raw"),
        F.col(incomg).cast("int").alias("incomg_raw"),
        (F.col(rfbing).cast("int") if rfbing else F.lit(None).cast("int")).alias("rfbing_raw"),
        (F.col(race_var).cast("int") if race_var else F.lit(None).cast("int")).alias("race_raw"),
        (F.col(mrace2).cast("int") if mrace2 else F.lit(None).cast("int")).alias("mrace2_raw"),
    )
    return out


def nullify(col: str, codes):
    """把指定编码替换为 NULL（返回 int 列表达式）。"""
    return F.when(F.col(col).isin([int(c) for c in codes]), F.lit(None)).otherwise(F.col(col)).cast("int")


def flag01(col: str, true_codes=(1,), false_codes=(2,)):
    """构造 0/1 标志位；不在 true/false 集合内（含 NULL）→ NULL。"""
    return (F.when(F.col(col).isin([int(c) for c in true_codes]), F.lit(1))
            .when(F.col(col).isin([int(c) for c in false_codes]), F.lit(0))
            .otherwise(F.lit(None)).cast("int"))


def clean(df):
    """执行全部清洗规则，返回 (清洗后 DataFrame, 审计指标 dict)。"""
    audit = {"rules": []}

    # ---------- 规则 1：缺失码 → NULL（逐变量指定，避免误伤合法取值）----------
    df = df.select(
        "*",
        nullify("age_grp", [14]).alias("age_grp_c"),
        nullify("hispanic", [9]).alias("hispanic_c"),
        nullify("educa", [9]).alias("educa_c"),
        nullify("employ", [9]).alias("employ_c"),
        nullify("marital", [9]).alias("marital_c"),
        nullify("veteran", [7, 9]).alias("veteran_c"),
        nullify("diabete4", [7, 9]).alias("diabete4_c"),
        nullify("cvdinfr4", [7, 9]).alias("cvdinfr4_c"),
        nullify("cvdchd4", [7, 9]).alias("cvdchd4_c"),
        nullify("cvdstrk3", [7, 9]).alias("cvdstrk3_c"),
        nullify("asthma3", [7, 9]).alias("asthma3_c"),
        nullify("chckdny2", [7, 9]).alias("chckdny2_c"),
        nullify("addep3", [7, 9]).alias("addep3_c"),
        nullify("copd_raw", [7, 9]).alias("copd_c"),
        nullify("genhlth_raw", [7, 9]).alias("genhlth_c"),
        nullify("rfhlth_raw", [9]).alias("rfhlth_c"),
        # 77=不知道 99=拒答 → NULL；88=“None”（0 天）是合法取值，保留后转 0
        nullify("menthlth_raw", [77, 99]).alias("menthlth_c"),
        nullify("physhlth_raw", [77, 99]).alias("physhlth_c"),
        nullify("checkup_raw", [7, 9]).alias("checkup_c"),      # 8=Never 合法
        nullify("diffwalk_raw", [7, 9]).alias("diffwalk_c"),
        nullify("smoker3_raw", [9]).alias("smoker3_c"),
        nullify("totinda_raw", [9]).alias("totinda_c"),
        nullify("medcost_raw", [7, 9]).alias("medcost_c"),
        nullify("persdoc_raw", [7, 9]).alias("persdoc_c"),
        nullify("rfbing_raw", [9]).alias("rfbing_c"),
    )

    # ---------- 规则 2：BMI = _BMI5/100，异常值 → NULL ----------
    df = df.withColumn(
        "bmi_raw", F.when(F.col("bmi5").isNull(), F.lit(None)).otherwise(F.col("bmi5") / F.lit(100.0))
    ).withColumn(
        "bmi", F.when((F.col("bmi_raw") < 10) | (F.col("bmi_raw") > 70), F.lit(None))
                    .otherwise(F.col("bmi_raw")).cast("double")
    )

    # ---------- 规则 3：收入分组调和（_INCOMG 5 档 ← _INCOMG1 7 档折叠）----------
    # _INCOMG : 1 <15k, 2 15-25k, 3 25-35k, 4 35-50k, 5 >=50k
    # _INCOMG1: 1 <15k, 2 15-25k, 3 25-35k, 4 35-50k, 5 50-100k, 6 100-200k, 7 >=200k
    df = df.withColumn(
        "income_grp",
        F.when(F.col("incomg_raw") == 9, F.lit(None))
         .when(F.col("incomg_raw").isin([6, 7]), F.lit(5))
         .otherwise(F.col("incomg_raw")).cast("int")
    )

    # ---------- 规则 3.5：二值字段统一 0/1（1 = 字段名所描述的状态成立）----------
    for src, dst in [("hispanic_c", "hispanic_n"), ("veteran_c", "veteran_n"),
                     ("medcost_c", "medcost_n"), ("diffwalk_c", "diffwalk_n")]:
        df = df.withColumn(dst, flag01(src, (1,), (2,)))

    # ---------- 规则 4：种族调和（_RACE 优先；2022 无 _RACE → _MRACE2 + _HISPANC）----------
    # _RACE  : 1 白人 2 黑人 3 印第安/阿拉斯加原住民 4 亚裔 5 夏威夷/太平洋岛民 6 其他 7 多种族 8 西班牙裔 9 DK
    # _MRACE2: 1 白人 2 黑人 3 印第安 4 亚裔 5 太平洋岛民 6 多种族 77 DK 88 未选 99 拒答
    race_from_mrace2 = (
        F.when(F.col("mrace2_raw").isin([77, 88, 99]), F.lit(None))
         .when(F.col("mrace2_raw") == 6, F.lit(7))          # 多种族
         .when(F.col("mrace2_raw").isin([1, 2, 3, 4, 5]), F.col("mrace2_raw"))
         .otherwise(F.lit(None))
    )
    df = df.withColumn(
        "race",
        F.when(F.col("race_raw").isNotNull(),
               F.when(F.col("race_raw") == 9, F.lit(None)).otherwise(F.col("race_raw")))
         .otherwise(
             F.when(F.col("hispanic_n") == 1, F.lit(8))       # 西班牙裔优先
              .otherwise(race_from_mrace2))
         .cast("int")
    )

    # ---------- 规则 5：8 个慢病标志位 ----------
    df = df.withColumn("has_diabetes", flag01("diabete4_c", (1,), (2, 3, 4)))   # 妊娠期/糖尿病前期均记为“否”
    df = df.withColumn("has_mi", flag01("cvdinfr4_c"))
    df = df.withColumn("has_chd", flag01("cvdchd4_c"))
    df = df.withColumn("has_stroke", flag01("cvdstrk3_c"))
    df = df.withColumn("has_copd", flag01("copd_c"))
    df = df.withColumn("has_asthma", flag01("asthma3_c"))
    df = df.withColumn("has_kidney", flag01("chckdny2_c"))
    df = df.withColumn("has_depression", flag01("addep3_c"))

    # ---------- 规则 6：派生指标 ----------
    flag_cols = [c for c, _ in CHRONIC_FLAGS]
    df = df.withColumn("chronic_count",
                       sum(F.coalesce(F.col(c), F.lit(0)) for c in flag_cols).cast("int"))
    df = df.withColumn("multimorbidity", (F.col("chronic_count") >= 2).cast("int"))
    all_null = F.lit(True)
    for c in flag_cols:
        all_null = all_null & F.col(c).isNull()
    df = df.withColumn("label_valid", F.when(all_null, F.lit(0)).otherwise(F.lit(1)).cast("int"))
    df = df.withColumn("obese",
                       F.when(F.col("bmi").isNull(), F.lit(None))
                        .otherwise((F.col("bmi") >= 30).cast("int")).cast("int"))

    # ---------- 规则 7：输出列整理（统一类型与顺序）----------
    df = df.withColumn("menthlth", F.when(F.col("menthlth_c") == 88, F.lit(0)).otherwise(F.col("menthlth_c")).cast("int")) \
           .withColumn("physhlth", F.when(F.col("physhlth_c") == 88, F.lit(0)).otherwise(F.col("physhlth_c")).cast("int"))

    final = df.select(
        # 主键：SEQNO 只在层内（_STSTR）唯一，必须带上层号才能全局唯一
        F.concat_ws("_", F.col("year").cast("string"), F.col("ststr").cast("string"),
                    F.col("seqno").cast("string")).alias("seq_key"),
        F.col("year"), F.col("month"), F.col("state_fips"),
        F.col("sex").cast("int").alias("sex"),
        F.col("age").cast("int").alias("age"),
        F.col("age_grp_c").alias("age_grp"),
        F.col("race"), F.col("hispanic_n").alias("hispanic"),
        F.col("educa_c").alias("educa"),
        F.col("income_grp"),
        F.col("employ_c").alias("employ"),
        F.col("marital_c").alias("marital"),
        F.col("veteran_n").alias("veteran"),
        F.col("bmi"), F.col("obese"),
        F.col("smoker3_c").alias("smoker3"),
        # 二值字段归一化为 0/1，1 = 字段名所描述的状态成立
        flag01("totinda_c", (1,), (2,)).alias("phys_activity"),   # _TOTINDA 1=有运动→1，2=无→0
        flag01("rfbing_c", (2,), (1,)).alias("heavy_drink"),      # _RFBING6 2=暴饮→1，1=否→0
        F.col("genhlth_c").alias("genhlth"),                      # 有序分类 1-5，保持原码
        flag01("rfhlth_c", (2,), (1,)).alias("poor_health"),      # _RFHLTH 2=一般/差→1，1=好→0
        F.col("menthlth"), F.col("physhlth"),
        F.col("checkup_c").alias("checkup"),
        F.col("medcost_n").alias("medcost"),
        F.col("persdoc_c").alias("persdoc"),
        F.col("diffwalk_n").alias("diffwalk"),
        *[F.col(c) for c in flag_cols],
        F.col("chronic_count"), F.col("multimorbidity"), F.col("label_valid"),
    )
    return final, audit


# 清洗后（最终口径）需要统计缺失率的关键字段
NULL_STATS_COLS = [
    "bmi", "smoker3", "phys_activity", "heavy_drink", "genhlth", "poor_health",
    "menthlth", "physhlth", "checkup", "medcost", "persdoc", "diffwalk",
    "race", "hispanic", "educa", "income_grp", "employ", "marital", "veteran", "age_grp",
] + [c for c, _ in CHRONIC_FLAGS]


# 清洗前：原始变量（含各年调和后的原始列名）
RAW_NULL_COLS = [
    "bmi5", "smoker3_raw", "totinda_raw", "rfbing_raw", "genhlth_raw", "rfhlth_raw",
    "menthlth_raw", "physhlth_raw", "checkup_raw", "medcost_raw", "persdoc_raw", "diffwalk_raw",
    "race_raw", "hispanic", "educa", "incomg_raw", "employ", "marital", "veteran", "age_grp",
    "diabete4", "cvdinfr4", "cvdchd4", "cvdstrk3", "copd_raw", "asthma3", "chckdny2", "addep3",
]


def null_rate_stats(df, cols):
    """一次聚合算出各字段缺失数（避免多次全表扫描）。"""
    exprs = [F.count(F.lit(1)).alias("_n")]
    for c in cols:
        exprs.append(F.sum(F.when(F.col(c).isNull(), 1).otherwise(0)).alias(c))
    row = df.agg(*exprs).collect()[0].asDict()
    n = row.pop("_n")
    return n, {k: int(v) for k, v in row.items()}


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
    os.makedirs(PROCESSED_DIR, exist_ok=True)

    spark = (SparkSession.builder
             .appName("brfss_clean")
             .master("local[4]")
             .config("spark.driver.memory", "6g")
             .config("spark.executor.memory", "6g")
             .config("spark.sql.shuffle.partitions", "8")
             .config("spark.ui.enabled", "false")
             .config("spark.sql.parquet.compression.codec", "snappy")
             .getOrCreate())
    spark.sparkContext.setLogLevel("WARN")
    log("Spark %s 启动完成" % spark.version)

    # ---------- 读取五年并合并 ----------
    frames = []
    rows_by_year_raw = {}
    for y in YEARS:
        p = os.path.join(RAW_DIR, "LLCP%d.parquet" % y)
        if not os.path.exists(p):
            log("缺少原始文件：%s（请先运行 01_download.py）" % p)
            return 1
        f = build_year_frame(spark, y)
        frames.append(f)
        rows_by_year_raw[y] = spark.read.parquet(p).count()
        log("已读取 %d：%d 行" % (y, rows_by_year_raw[y]))

    union = frames[0]
    for f in frames[1:]:
        union = union.unionByName(f)
    n_raw = sum(rows_by_year_raw.values())
    union = union.persist()          # 多轮聚合复用，避免重复读 5 个 parquet
    n_union = union.count()
    log("五年合并完成：%d 行（各年合计 %d），已缓存" % (n_union, n_raw))
    raw_null_n, raw_null = null_rate_stats(union, RAW_NULL_COLS)

    # ---------- 清洗 ----------
    cleaned, _ = clean(union)

    # BMI 异常计数（清洗前后）
    bmi_anomaly = cleaned.filter(
        F.col("bmi").isNull() & F.col("bmi_raw").isNotNull() &
        ((F.col("bmi_raw") < 10) | (F.col("bmi_raw") > 70))
    ).count()
    bmi_missing = cleaned.filter(F.col("bmi_raw").isNull()).count()

    # 标签不可用行（8 个标志位全 NULL）
    label_invalid = cleaned.filter(F.col("label_valid") == 0).count()

    valid = cleaned.filter(F.col("label_valid") == 1).drop("bmi_raw", "label_valid")
    n_valid = valid.count()
    valid_null_n, valid_null = null_rate_stats(valid, NULL_STATS_COLS)
    log("剔除标签不可用 %d 行后剩余 %d 行" % (label_invalid, n_valid))

    # 每步丢弃行数（写入审计）
    drop_rules = [{
        "rule": "label_all_null",
        "desc": "8 个慢病标志位全为 NULL（标签不可用）",
        "rows": int(label_invalid),
    }]
    keep_rules = [
        {"rule": "bmi_out_of_range", "desc": "BMI<10 或 >70 → 置 NULL（不丢行）", "rows": int(bmi_anomaly)},
        {"rule": "bmi_missing", "desc": "_BMI5 原始缺失 → bmi 为 NULL（不丢行）", "rows": int(bmi_missing)},
    ]

    # ---------- 写出单文件 parquet（Arrow 分批流式落盘）----------
    if os.path.exists(OUT_FILE):
        os.remove(OUT_FILE)
    n_written = write_parquet_via_arrow(valid, OUT_FILE)
    size_bytes = os.path.getsize(OUT_FILE)
    log("已写出 %s（%.1f MB，%d 行）" % (OUT_FILE, size_bytes / 1024 / 1024, n_written))
    union.unpersist()

    # ---------- 写出后回读校验 + 各年行数 ----------
    check = spark.read.parquet(OUT_FILE)
    n_out = check.count()
    if n_out != n_valid:
        raise RuntimeError("回读行数 %d ≠ 期望 %d" % (n_out, n_valid))
    n_key_distinct = check.select("seq_key").distinct().count()
    if n_key_distinct != n_out:
        raise RuntimeError("seq_key 不唯一：distinct=%d / total=%d" % (n_key_distinct, n_out))
    log("seq_key 唯一性校验通过：%d / %d" % (n_key_distinct, n_out))
    rows_by_year = {str(r["year"]): int(r["count"]) for r in
                    check.groupBy("year").count().orderBy("year").collect()}
    chronic_prevalence = {}
    for c, label in CHRONIC_FLAGS:
        pos = check.filter(F.col(c) == 1).count()
        nnt = check.filter(F.col(c).isNotNull()).count()
        chronic_prevalence[c] = {"name_cn": label, "n_positive": int(pos), "n_valid": int(nnt),
                                 "prevalence": round(pos / nnt, 6) if nnt else None}
    for c in ["multimorbidity"]:
        pos = check.filter(F.col(c) == 1).count()
        chronic_prevalence[c] = {"name_cn": "共病（慢病数≥2）", "n_positive": int(pos),
                                 "n_valid": int(n_out), "prevalence": round(pos / n_out, 6)}
    log("清洗后行数 %d；共病率 %.4f" % (n_out, chronic_prevalence["multimorbidity"]["prevalence"]))
    spark.stop()

    elapsed = round(time.time() - t_start, 1)
    step = {
        "step": "02_clean_spark",
        "label": "PySpark 清洗与派生指标",
        "started_at": datetime.fromtimestamp(t_start).astimezone().isoformat(timespec="seconds"),
        "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "elapsed_sec": elapsed,
        "engine": "pyspark %s local[4] driver.memory=6g" % __import__("pyspark").__version__,
        "rows_in": int(n_raw),
        "rows_in_by_year": {str(k): int(v) for k, v in rows_by_year_raw.items()},
        "rows_union": int(n_union),
        "rows_out": int(n_out),
        "rows_out_by_year": rows_by_year,
        "seq_key_distinct": int(n_key_distinct),
        "drop_rules": drop_rules,
        "value_rules": keep_rules,
        "rows_dropped_total": int(n_raw - n_out),
        "output_file": os.path.relpath(OUT_FILE, ROOT).replace("\\", "/"),
        "output_writer": "pyarrow streaming (winutils unavailable, Spark DataFrameWriter disabled)",
        "output_bytes": int(size_bytes),
        "null_count_before": raw_null,
        "null_count_after": valid_null,
        "null_rate_after": {k: round(v / n_valid, 6) for k, v in valid_null.items()},
        "chronic_prevalence": chronic_prevalence,
        "columns": len(check.columns),
    }
    append_pipeline_log(step)
    log("清洗完成，耗时 %.1f 秒；审计已写入 %s" % (elapsed, LOG_PATH))
    return 0


if __name__ == "__main__":
    sys.exit(main())
