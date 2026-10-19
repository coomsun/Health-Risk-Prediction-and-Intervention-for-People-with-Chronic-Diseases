#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""05_train.py — 预测建模与对比实验

切分：时间外推 train=2019-2022 / test=2023（贴近真实部署，比随机切分更严格）
模型：LogisticRegression / RandomForest / LightGBM
特征集：Set-A（可干预，无泄漏） vs Set-B（含健康状态后果变量，性能上限）
主模型：LightGBM @ Set-A —— 无标签泄漏、可直接用于干预决策，供 /api/v1/predict 使用
输出：artifacts/model/model.joblib、feature_names.json、model_meta.json、metrics.json
      与 db 的 model_metrics 表、artifacts/figures/model/*.png
"""
import json
import os
import sqlite3
import sys
import time
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.calibration import calibration_curve
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, average_precision_score, brier_score_loss,
                             confusion_matrix, f1_score, recall_score, roc_auc_score, roc_curve)
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MDIR = os.path.join(ROOT, "artifacts", "model")
FDIR = os.path.join(ROOT, "artifacts", "figures", "model")
DB = os.path.join(ROOT, "db", "chronic_risk.db")
LABEL = "multimorbidity"


def load_sets():
    with open(os.path.join(MDIR, "features_A.json"), encoding="utf-8") as f:
        fa = json.load(f)
    with open(os.path.join(MDIR, "features_B.json"), encoding="utf-8") as f:
        fb = json.load(f)
    return fa["features"], fb["features"]


def make_models(neg_pos_ratio):
    lr = Pipeline([
        ("imp", SimpleImputer(strategy="median")),
        ("sc", StandardScaler()),
        ("clf", LogisticRegression(max_iter=1000, class_weight="balanced", solver="lbfgs", n_jobs=-1)),
    ])
    rf = Pipeline([
        ("imp", SimpleImputer(strategy="median")),
        ("clf", RandomForestClassifier(n_estimators=120, max_depth=16, min_samples_leaf=20,
                                       class_weight="balanced_subsample", max_samples=0.6,
                                       n_jobs=-1, random_state=42)),
    ])
    import lightgbm as lgb
    gbm = lgb.LGBMClassifier(
        n_estimators=450, learning_rate=0.05, num_leaves=63, min_child_samples=100,
        subsample=0.8, colsample_bytree=0.8, scale_pos_weight=neg_pos_ratio,
        n_jobs=-1, random_state=42, verbose=-1,
    )
    return {"LogisticRegression": lr, "RandomForest": rf, "LightGBM": gbm}


def evaluate(y, prob, thr=0.5):
    pred = (prob >= thr).astype(int)
    return {
        "auc_roc": float(roc_auc_score(y, prob)),
        "auc_pr": float(average_precision_score(y, prob)),
        "f1": float(f1_score(y, pred)),
        "accuracy": float(accuracy_score(y, pred)),
        "recall": float(recall_score(y, pred)),
        "brier": float(brier_score_loss(y, prob)),
        "positive_rate_pred": float(pred.mean()),
    }


def plot_roc(curves, path):
    fig, ax = plt.subplots(figsize=(7.2, 6))
    for label, (fpr, tpr, auc) in curves.items():
        ax.plot(fpr, tpr, lw=1.6, label="%s (AUC=%.4f)" % (label, auc))
    ax.plot([0, 1], [0, 1], "k--", lw=1, label="随机基线")
    ax.set_xlabel("假阳性率 FPR"); ax.set_ylabel("真阳性率 TPR")
    ax.set_title("共病预测 ROC 曲线（测试集=2023 年，n=%s）" % "{:,}".format(curves["_n"]))
    ax.legend(loc="lower right", fontsize=9); ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(path, dpi=300, bbox_inches="tight", facecolor="white"); plt.close(fig)


def plot_pr(curves, base, n, path):
    fig, ax = plt.subplots(figsize=(7.2, 6))
    for label, (rec, prec, ap) in curves.items():
        ax.plot(rec, prec, lw=1.6, label="%s (PR-AUC=%.4f)" % (label, ap))
    ax.axhline(base, color="grey", ls="--", lw=1, label="正例基准率 %.4f" % base)
    ax.set_xlabel("召回率 Recall"); ax.set_ylabel("精确率 Precision")
    ax.set_title("共病预测 PR 曲线（测试集 2023，n=%s）" % "{:,}".format(n))
    ax.legend(loc="upper right", fontsize=9); ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(path, dpi=300, bbox_inches="tight", facecolor="white"); plt.close(fig)


def plot_importance(model, feats, path, top=15):
    imp = pd.Series(model.feature_importances_, index=feats).sort_values(ascending=True).tail(top)
    fig, ax = plt.subplots(figsize=(8, 6.2))
    ax.barh(imp.index, imp.values, color="#3b6ea5")
    ax.set_xlabel("特征重要性（分裂增益，任意单位）")
    ax.set_title("LightGBM 特征重要性 Top%d（Set-A 可干预特征集）" % top)
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout(); fig.savefig(path, dpi=300, bbox_inches="tight", facecolor="white"); plt.close(fig)


def plot_calibration(y, prob, path, n):
    frac, mean_pred = calibration_curve(y, prob, n_bins=12, strategy="quantile")
    fig, ax = plt.subplots(figsize=(6.4, 6))
    ax.plot(mean_pred, frac, "o-", lw=1.6, label="LightGBM (Set-A)")
    ax.plot([0, 1], [0, 1], "k--", lw=1, label="完美校准")
    ax.set_xlabel("预测概率均值（分箱）"); ax.set_ylabel("实际共病发生率")
    ax.set_title("校准曲线（测试集 2023，n=%s）" % "{:,}".format(n))
    ax.legend(loc="upper left", fontsize=9); ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(path, dpi=300, bbox_inches="tight", facecolor="white"); plt.close(fig)


def plot_confusion(y, prob, path):
    cm = confusion_matrix(y, (prob >= 0.5).astype(int))
    fig, ax = plt.subplots(figsize=(5.6, 4.8))
    im = ax.imshow(cm, cmap="Blues")
    for i in range(2):
        for j in range(2):
            ax.text(j, i, "{:,}".format(cm[i, j]), ha="center", va="center",
                    color="white" if cm[i, j] > cm.max() / 2 else "black", fontsize=13)
    ax.set_xticks([0, 1]); ax.set_yticks([0, 1])
    ax.set_xticklabels(["预测:非共病", "预测:共病"]); ax.set_yticklabels(["实际:非共病", "实际:共病"])
    ax.set_title("混淆矩阵（阈值=0.5，测试集 2023）")
    fig.colorbar(im, ax=ax, fraction=0.046); fig.tight_layout()
    fig.savefig(path, dpi=300, bbox_inches="tight", facecolor="white"); plt.close(fig)


def main() -> int:
    t0 = time.time()
    os.makedirs(FDIR, exist_ok=True)
    feats_a, feats_b = load_sets()
    df = pd.read_parquet(os.path.join(MDIR, "dataset.parquet"))
    print("[1/6] 数据集 %d 行" % len(df))

    tr = df[df["year"] <= 2022]
    te = df[df["year"] == 2023]
    ytr, yte = tr[LABEL].to_numpy(), te[LABEL].to_numpy()
    neg_pos = float((ytr == 0).sum()) / max(1, (ytr == 1).sum())
    print("      train(2019-2022)=%d 正例率=%.4f | test(2023)=%d 正例率=%.4f | neg/pos=%.2f"
          % (len(tr), ytr.mean(), len(te), yte.mean(), neg_pos))

    results, probs, roc_cv, pr_cv, deploy = [], {}, {}, {}, None
    print("[2/6] 训练 6 个组合（2 特征集 × 3 模型）...")
    for sname, feats in (("SetA", feats_a), ("SetB", feats_b)):
        Xtr = tr[feats].astype("float32"); Xte = te[feats].astype("float32")
        for mname, model in make_models(neg_pos).items():
            key = "%s_%s" % (mname, sname)
            ts = time.time()
            model.fit(Xtr, ytr)
            prob = model.predict_proba(Xte)[:, 1]
            m = evaluate(yte, prob)
            m.update({"model": key, "feature_set": sname, "n_features": len(feats),
                      "fit_seconds": round(time.time() - ts, 1)})
            results.append(m); probs[key] = prob
            fpr, tpr, _ = roc_curve(yte, prob)
            roc_cv[key] = (fpr, tpr, m["auc_roc"])
            from sklearn.metrics import precision_recall_curve
            pre, rec, _ = precision_recall_curve(yte, prob)
            pr_cv[key] = (rec, pre, m["auc_pr"])
            print("      %-24s AUC=%.4f  PR-AUC=%.4f  F1=%.4f  (%.0fs)"
                  % (key, m["auc_roc"], m["auc_pr"], m["f1"], time.time() - ts))
            if key == "LightGBM_SetA":
                deploy = model

    print("[3/6] 主模型 5 折交叉验证（Set-A / LightGBM）...")
    cv_scores = []
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    Xtr_a = tr[feats_a].astype("float32")
    for k, (i_tr, i_va) in enumerate(skf.split(Xtr_a, ytr), 1):
        mdl = make_models(neg_pos)["LightGBM"]
        mdl.fit(Xtr_a.iloc[i_tr], ytr[i_tr])
        s = roc_auc_score(ytr[i_va], mdl.predict_proba(Xtr_a.iloc[i_va])[:, 1])
        cv_scores.append(float(s))
        print("      fold%d AUC=%.4f" % (k, s))
    cv_mean, cv_std = float(np.mean(cv_scores)), float(np.std(cv_scores))
    print("      CV AUC = %.4f ± %.4f" % (cv_mean, cv_std))

    print("[4/6] 保存模型与元数据 ...")
    import joblib
    joblib.dump(deploy, os.path.join(MDIR, "model.joblib"))
    with open(os.path.join(MDIR, "feature_names.json"), "w", encoding="utf-8") as f:
        json.dump({"features": feats_a, "set": "A", "label": LABEL,
                   "model": "LightGBM", "note": "Set-A 可干预特征集，无标签泄漏；原生支持缺失值"},
                  f, ensure_ascii=False, indent=2)
    best = [r for r in results if r["model"] == "LightGBM_SetA"][0]
    meta = {"primary_model": "LightGBM_SetA", "label": LABEL,
            "train_years": [2019, 2020, 2021, 2022], "test_year": 2023,
            "n_train": int(len(tr)), "n_test": int(len(te)),
            "test_positive_rate": float(yte.mean()),
            "cv_auc_mean": cv_mean, "cv_auc_std": cv_std,
            "metrics": best, "features": feats_a}
    with open(os.path.join(MDIR, "model_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    with open(os.path.join(MDIR, "metrics.json"), "w", encoding="utf-8") as f:
        json.dump({"cv_auc_scores": cv_scores, "results": results}, f, ensure_ascii=False, indent=2)
    print("      model.joblib / feature_names.json / model_meta.json / metrics.json 已写入")

    print("[5/6] 写入 db model_metrics 表 ...")
    conn = sqlite3.connect(DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS model_metrics (
        model_name TEXT NOT NULL, metric TEXT NOT NULL, value REAL,
        PRIMARY KEY (model_name, metric))""")
    rows = []
    for r in results:
        for k in ("auc_roc", "auc_pr", "f1", "accuracy", "recall", "brier"):
            rows.append((r["model"], k, float(r[k])))
    rows.append(("LightGBM_SetA", "cv_auc_mean", cv_mean))
    rows.append(("LightGBM_SetA", "cv_auc_std", cv_std))
    conn.executemany("INSERT OR REPLACE INTO model_metrics(model_name, metric, value) VALUES (?,?,?)", rows)
    conn.commit()
    nrow = conn.execute("SELECT COUNT(*) FROM model_metrics").fetchone()[0]
    conn.close()
    print("      model_metrics 写入 %d 行（表内共 %d 行）" % (len(rows), nrow))

    print("[6/6] 出图 ...")
    curv = {k: v for k, v in roc_cv.items()}
    curv["_n"] = len(te)

    def _plot_roc(c, path):
        fig, ax = plt.subplots(figsize=(7.2, 6))
        for label, val in c.items():
            if label == "_n" or not isinstance(val, tuple):
                continue
            fpr, tpr, auc = val
            ax.plot(fpr, tpr, lw=1.5, label="%s (AUC=%.4f)" % (label, auc))
        ax.plot([0, 1], [0, 1], "k--", lw=1, label="随机基线")
        ax.set_xlabel("假阳性率 FPR"); ax.set_ylabel("真阳性率 TPR")
        ax.set_title("共病预测 ROC 曲线（测试集=2023，n=%s）" % "{:,}".format(c["_n"]))
        ax.legend(loc="lower right", fontsize=8); ax.grid(alpha=0.3)
        fig.tight_layout(); fig.savefig(path, dpi=300, bbox_inches="tight", facecolor="white"); plt.close(fig)

    _plot_roc(curv, os.path.join(FDIR, "roc_comparison.png"))
    plot_pr(pr_cv, float(yte.mean()), len(te), os.path.join(FDIR, "pr_curve.png"))
    plot_importance(deploy, feats_a, os.path.join(FDIR, "feature_importance.png"))
    plot_calibration(yte, probs["LightGBM_SetA"], os.path.join(FDIR, "calibration.png"), len(te))
    plot_confusion(yte, probs["LightGBM_SetA"], os.path.join(FDIR, "confusion_matrix.png"))
    print("      5 张图已写入 artifacts/figures/model/")

    print("\n===== 对比实验汇总（测试集 2023）=====")
    hdr = "%-24s %8s %8s %8s %8s" % ("模型", "AUC", "PR-AUC", "F1", "Brier")
    print(hdr)
    for r in sorted(results, key=lambda x: -x["auc_roc"]):
        print("%-24s %8.4f %8.4f %8.4f %8.4f" % (r["model"], r["auc_roc"], r["auc_pr"], r["f1"], r["brier"]))
    a = [r for r in results if r["feature_set"] == "SetA" and r["model"] == "LightGBM_SetA"][0]
    b = [r for r in results if r["feature_set"] == "SetB" and r["model"] == "LightGBM_SetB"][0]
    print("\n特征集对比（LightGBM）：Set-A AUC=%.4f vs Set-B AUC=%.4f，差 %.4f"
          % (a["auc_roc"], b["auc_roc"], b["auc_roc"] - a["auc_roc"]))
    print("总耗时 %.1fs" % (time.time() - t0))
    print("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
