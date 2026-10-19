#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""07_spark_mllib.py — 报告模板 4.2「路径B：Spark MLlib（传统 ML）」

与 05_train.py 的 sklearn/LightGBM 结果互为交叉验证：
同一份 data/processed/brfss_clean.parquet、同一时间外推切分（train 2019-2022 / test 2023），
用 Spark MLlib 训练 LogisticRegression 与 GBTClassifier，输出 AUC 供报告对比。
注意：本机缺 winutils.exe，故只读 parquet、不落 Spark 文件；结果写 JSON。
"""
import json
import os
import sys
import time

os.environ.setdefault("JAVA_HOME", r"D:\jdk17")
os.environ.setdefault("SPARK_HOME", r"D:\sparkhome")

from pyspark.ml import Pipeline
from pyspark.ml.classification import GBTClassifier, LogisticRegression
from pyspark.ml.evaluation import BinaryClassificationEvaluator
from pyspark.ml.feature import Imputer, StandardScaler, VectorAssembler
from pyspark.sql import SparkSession, functions as F

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "processed", "brfss_clean.parquet")
OUT = os.path.join(ROOT, "artifacts", "metrics", "spark_mllib_metrics.json")

FEATURES = ["year", "state_fips", "sex", "age", "race", "hispanic", "educa",
            "income_grp", "employ", "marital", "veteran", "bmi", "obese",
            "smoker3", "phys_activity", "heavy_drink", "medcost", "checkup", "persdoc"]
LABEL = "multimorbidity"


def main() -> int:
    t0 = time.time()
    spark = (SparkSession.builder.appName("brfss_mllib").master("local[8]")
             .config("spark.driver.memory", "6g")
             .config("spark.ui.enabled", "false")
             .config("spark.sql.shuffle.partitions", "16")
             .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")
    df = spark.read.parquet(SRC).select(FEATURES + [LABEL])
    df = df.fillna({c: None for c in []}).na.drop(subset=[LABEL])
    tr = df.filter(F.col("year") <= 2022)
    te = df.filter(F.col("year") == 2023)
    n_tr, n_te = tr.count(), te.count()
    print("[1/3] train=%d test=%d" % (n_tr, n_te))

    # Spark MLlib 的线性模型不接受 NaN（不同于 LightGBM），先用中位数填补
    imp_cols = [c + "_imp" for c in FEATURES]
    imputer = Imputer(inputCols=FEATURES, outputCols=imp_cols, strategy="median")
    va = VectorAssembler(inputCols=imp_cols, outputCol="raw", handleInvalid="skip")
    sc = StandardScaler(inputCol="raw", outputCol="features", withMean=True, withStd=True)
    ev = BinaryClassificationEvaluator(rawPredictionCol="rawPrediction",
                                       labelCol=LABEL, metricName="areaUnderROC")
    results = []
    for name, clf, use_scale in (
        ("SparkMLlib_LogisticRegression", LogisticRegression(maxIter=30, regParam=0.01,
                                                             standardization=False,
                                                             labelCol=LABEL, featuresCol="features"), True),
        ("SparkMLlib_GBTClassifier", GBTClassifier(maxIter=40, maxDepth=6, stepSize=0.1,
                                                   subsamplingRate=0.8, seed=42,
                                                   labelCol=LABEL, featuresCol="raw"), False),
    ):
        ts = time.time()
        stages = [imputer, va] + ([sc] if use_scale else [])
        pipe = Pipeline(stages=stages + [clf])
        model = pipe.fit(tr)
        pred = model.transform(te)
        auc = ev.evaluate(pred)
        acc = pred.filter(F.col("prediction") == F.col(LABEL)).count() / float(n_te)
        tp = pred.filter((F.col("prediction") == 1) & (F.col(LABEL) == 1)).count()
        fp = pred.filter((F.col("prediction") == 1) & (F.col(LABEL) == 0)).count()
        fn = pred.filter((F.col("prediction") == 0) & (F.col(LABEL) == 1)).count()
        prec = tp / float(tp + fp) if tp + fp else 0.0
        rec = tp / float(tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        results.append({"model": name, "auc_roc": round(float(auc), 6),
                        "accuracy": round(float(acc), 6), "precision": round(prec, 6),
                        "recall": round(float(rec), 6), "f1": round(f1, 6),
                        "train_rows": int(n_tr), "test_rows": int(n_te),
                        "fit_seconds": round(time.time() - ts, 1), "features": FEATURES})
        print("      %-32s AUC=%.4f  F1=%.4f  (%.0fs)" % (name, auc, f1, time.time() - ts))
    spark.stop()
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"engine": "Spark MLlib (pyspark 4.2.0, local[8])",
                   "split": "train 2019-2022 / test 2023",
                   "results": results, "elapsed_sec": round(time.time() - t0, 1)},
                  f, ensure_ascii=False, indent=2)
    print("[3/3] 已写出 %s" % OUT)
    print("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
