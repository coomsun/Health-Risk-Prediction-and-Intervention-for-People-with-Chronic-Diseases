#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""04_features.py — 特征工程

构造两个特征集（口径见 _设计规格.md 与 docs/建模说明.md）：
  Set-A 可干预生活方式 + 社会人口学：不含疾病"后果"类变量，无标签泄漏，可用于实际干预
  Set-B 全特征：Set-A + 自身健康状态类变量（genhlth/poor_health/menthlth/physhlth/diffwalk）

标签：multimorbidity = chronic_count >= 2
输出：artifacts/model/dataset.parquet 与 features_A.json / features_B.json
"""
import json
import os
import sqlite3
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "db", "chronic_risk.db")
OUT = os.path.join(ROOT, "artifacts", "model")

# 可干预生活方式 + 社会人口学（无后果类变量）
FEATURES_A = [
    "year", "state_fips", "sex", "age", "race", "hispanic", "educa",
    "income_grp", "employ", "marital", "veteran", "bmi", "obese",
    "smoker3", "phys_activity", "heavy_drink", "medcost", "checkup", "persdoc",
]
# 追加自身健康状态（疾病的后果，存在标签泄漏风险，仅用于对比上限）
CONSEQUENCE = ["genhlth", "poor_health", "menthlth", "physhlth", "diffwalk"]
FEATURES_B = FEATURES_A + CONSEQUENCE

LABEL = "multimorbidity"


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    if not os.path.exists(DB):
        print("[ERR] 数据库不存在：%s" % DB)
        return 2

    cols = ["year", LABEL, "chronic_count"] + FEATURES_B
    cols = list(dict.fromkeys(cols))
    conn = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    print("[1/3] 从 fact_brfss 读取 %d 列 ..." % len(cols))
    df = pd.read_sql_query("SELECT %s FROM fact_brfss" % ", ".join(cols), conn)
    conn.close()
    print("      行数 = %d, 列数 = %d" % (len(df), df.shape[1]))

    # 标签必须非空
    before = len(df)
    df = df[df[LABEL].notna()].copy()
    print("      标签非空过滤：%d -> %d" % (before, len(df)))

    # 数值型统一 float32 降内存；类别型保留原码
    for c in FEATURES_B:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    df[LABEL] = df[LABEL].astype("int8")
    df["year"] = df["year"].astype("int16")

    print("[2/3] 标签分布：")
    vc = df[LABEL].value_counts().sort_index()
    for k, v in vc.items():
        print("      %s: %d (%.2f%%)" % (k, v, 100.0 * v / len(df)))

    print("[3/3] 缺失率 Top8：")
    miss = (df[FEATURES_B].isna().mean() * 100).sort_values(ascending=False).head(8)
    for k, v in miss.items():
        print("      %-16s %6.2f%%" % (k, v))

    out_parquet = os.path.join(OUT, "dataset.parquet")
    df.to_parquet(out_parquet, index=False)
    print("      已写入 %s (%.1f MB)" % (out_parquet, os.path.getsize(out_parquet) / 1024 / 1024))

    with open(os.path.join(OUT, "features_A.json"), "w", encoding="utf-8") as f:
        json.dump({"set": "A", "label": LABEL, "features": FEATURES_A}, f, ensure_ascii=False, indent=2)
    with open(os.path.join(OUT, "features_B.json"), "w", encoding="utf-8") as f:
        json.dump({"set": "B", "label": LABEL, "features": FEATURES_B}, f, ensure_ascii=False, indent=2)
    print("      已写入 features_A.json / features_B.json")
    print("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
