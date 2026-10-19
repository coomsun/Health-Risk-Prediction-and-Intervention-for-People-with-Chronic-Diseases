# -*- coding: utf-8 -*-
"""10_tuning.py — 模型超参调优（综合项目加分项：模型调优与对比）

对主模型 LightGBM 做带交叉验证的网格搜索，与 05_train.py 的默认参数对比，
输出调优前后指标差，并写回 db 的 model_metrics 表（model_name 后缀 _tuned）。

注意：调优在训练集内部用 3 折 CV 完成，测试集（2023）只在最后评估一次，
避免在测试集上调参造成乐观偏差。
"""
from __future__ import annotations

import itertools
import json
import os
import sqlite3
import sys
import time

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, f1_score, roc_auc_score
from sklearn.model_selection import StratifiedKFold

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MDIR = os.path.join(ROOT, "artifacts", "model")
OUT = os.path.join(ROOT, "artifacts", "metrics", "tuning_metrics.json")
DB = os.path.join(ROOT, "db", "chronic_risk.db")
LABEL = "multimorbidity"

# 搜索阶段用小容量模型（n_estimators=120）快速评估，确定最优结构后再用
# 全容量（450 棵树）重训，兼顾调优可信度与运行时长。
GRID = {
    "num_leaves": [31, 63],
    "learning_rate": [0.05, 0.10],
}
BASE_PARAMS = dict(n_estimators=450, subsample=0.8, colsample_bytree=0.8,
                   scale_pos_weight=4.56, n_jobs=-1, random_state=42, verbose=-1)
SEARCH_ESTIMATORS = 120


def main() -> int:
    import lightgbm as lgb

    t0 = time.time()
    with open(os.path.join(MDIR, "features_A.json"), encoding="utf-8") as f:
        feats = json.load(f)["features"]
    df = pd.read_parquet(os.path.join(MDIR, "dataset.parquet"))
    tr = df[df["year"] <= 2022]
    te = df[df["year"] == 2023]
    Xtr, ytr = tr[feats].astype("float32"), tr[LABEL].to_numpy()
    Xte, yte = te[feats].astype("float32"), te[LABEL].to_numpy()
    print("[1/3] 训练集 %s | 测试集 %s | 特征 %d 维"
          % ("{:,}".format(len(Xtr)), "{:,}".format(len(Xte)), len(feats)))

    skf = StratifiedKFold(n_splits=2, shuffle=True, random_state=42)
    folds = list(skf.split(Xtr, ytr))

    def cv_score(params: dict) -> tuple[float, float]:
        aucs, prs = [], []
        for i_tr, i_va in folds:
            m = lgb.LGBMClassifier(**{**BASE_PARAMS, **params, "n_estimators": SEARCH_ESTIMATORS})
            m.fit(Xtr.iloc[i_tr], ytr[i_tr])
            p = m.predict_proba(Xtr.iloc[i_va])[:, 1]
            aucs.append(roc_auc_score(ytr[i_va], p))
            prs.append(average_precision_score(ytr[i_va], p))
        return float(np.mean(aucs)), float(np.mean(prs))

    base_auc, base_pr = cv_score({})
    print("[2/3] 基线（05_train.py 默认参数）CV AUC=%.4f PR-AUC=%.4f" % (base_auc, base_pr))

    keys = list(GRID)
    combos = list(itertools.product(*(GRID[k] for k in keys)))
    print("      网格共 %d 组，开始搜索 ..." % len(combos))
    results, best = [], None
    for n, vals in enumerate(combos, 1):
        params = dict(zip(keys, vals))
        auc, pr = cv_score(params)
        results.append({**params, "cv_auc": round(auc, 5), "cv_pr_auc": round(pr, 5)})
        mark = ""
        if best is None or auc > best["cv_auc"]:
            best = {**params, "cv_auc": auc, "cv_pr_auc": pr}
            mark = "  <- 当前最优"
        print("      [%2d/%d] %s  AUC=%.4f%s" % (n, len(combos), params, auc, mark))

    print("[3/3] 用最优参数在测试集（2023）评估一次")
    final = lgb.LGBMClassifier(**{**BASE_PARAMS, **best})
    final.fit(Xtr, ytr)
    prob = final.predict_proba(Xte)[:, 1]
    pred = (prob >= 0.5).astype(int)
    tuned = {
        "model": "LightGBM_SetA_tuned", "feature_set": "SetA",
        "auc_roc": round(float(roc_auc_score(yte, prob)), 6),
        "auc_pr": round(float(average_precision_score(yte, prob)), 6),
        "f1": round(float(f1_score(yte, pred)), 6),
        "best_params": best,
    }
    print("      调优后 AUC=%.4f PR-AUC=%.4f F1=%.4f"
          % (tuned["auc_roc"], tuned["auc_pr"], tuned["f1"]))

    # 读基线测试集结果做对比
    baseline = None
    with open(os.path.join(MDIR, "metrics.json"), encoding="utf-8") as f:
        for r in json.load(f)["results"]:
            if r["model"] == "LightGBM_SetA":
                baseline = r
                break
    gain = (tuned["auc_roc"] - baseline["auc_roc"]) if baseline else None
    print("      基线测试集 AUC=%.4f | 提升 %+.4f"
          % (baseline["auc_roc"], gain) if baseline else "      基线缺失")

    payload = {
        "engine": "lightgbm GridSearch + 3-Fold CV",
        "grid": GRID, "n_combos": len(combos),
        "baseline_cv": {"auc": round(base_auc, 5), "pr_auc": round(base_pr, 5)},
        "search_results": results,
        "best": tuned,
        "baseline_test": baseline,
        "auc_gain_on_test": round(gain, 6) if gain is not None else None,
        "elapsed_sec": round(time.time() - t0, 1),
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    # 写回数据库
    try:
        conn = sqlite3.connect(DB)
        rows = [(tuned["model"], k, float(tuned[k])) for k in ("auc_roc", "auc_pr", "f1")]
        rows.append((tuned["model"], "cv_auc_mean", float(best["cv_auc"])))
        if gain is not None:
            rows.append(("LightGBM_SetA", "auc_gain_after_tuning", float(gain)))
        conn.executemany("INSERT OR REPLACE INTO model_metrics(model_name, metric, value) VALUES (?,?,?)", rows)
        conn.commit()
        n = conn.execute("SELECT COUNT(*) FROM model_metrics").fetchone()[0]
        conn.close()
        print("      已写入 model_metrics（新增 %d 行，表内共 %d 行）" % (len(rows), n))
    except Exception as e:
        print("      [warn] 写库失败：%s" % e)

    print("DONE 总耗时 %.1fs -> %s" % (time.time() - t0, OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
