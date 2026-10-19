# -*- coding: utf-8 -*-
"""11_seaborn_figures.py — Seaborn 统计可视化（综合项目加分项：Matplotlib / Seaborn 出图）

与 03_eda_spark.py 的 matplotlib 图互补：本脚本侧重统计分布与关系探索，
输出到 artifacts/figures/seaborn/，供报告与 PPT 引用。
"""
from __future__ import annotations

import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MDIR = os.path.join(ROOT, "artifacts", "model")
OUT = os.path.join(ROOT, "artifacts", "figures", "seaborn")
LABEL = "multimorbidity"

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False
sns.set_theme(style="whitegrid", font="Microsoft YaHei", rc={"axes.unicode_minus": False})


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(MDIR, "features_A.json"), encoding="utf-8") as f:
        feats = json.load(f)["features"]
    # 注意 feats 本身已含 year，重复列会导致 pandas 返回二维块，必须先按序去重
    cols = list(dict.fromkeys(feats + [LABEL, "year"]))
    df = pd.read_parquet(os.path.join(MDIR, "dataset.parquet"), columns=cols)
    print("载入 %s 行 × %d 列" % ("{:,}".format(len(df)), len(df.columns)))

    # 为可读性抽样（绘图不必用全量，2% 足以呈现分布形态）
    smp = df.sample(n=min(60000, len(df)), random_state=42)
    print("绘图层抽样 %s 行" % "{:,}".format(len(smp)))
    made = []

    # 1) 相关性热力图（Seaborn heatmap）
    num = [c for c in ["age", "bmi", "genhlth", "menthlth", "physhlth", "chronic_count"]
           if c in df.columns]
    if len(num) >= 3:
        corr = smp[num].corr(method="spearman")
        fig, ax = plt.subplots(figsize=(7.2, 6))
        sns.heatmap(corr, annot=True, fmt=".2f", cmap="RdBu_r", center=0,
                    square=True, linewidths=0.5, ax=ax, cbar_kws={"shrink": .8})
        ax.set_title(f"关键数值变量 Spearman 相关矩阵（抽样 n={len(smp):,}）")
        p = os.path.join(OUT, "sns_corr_heatmap.png")
        fig.tight_layout(); fig.savefig(p, dpi=300, bbox_inches="tight"); plt.close(fig)
        made.append(p)

    # 2) 共病率按吸烟状态（Seaborn barplot + 置信区间）
    if "smoker3" in smp.columns:
        g = smp.dropna(subset=["smoker3"]).copy()
        g["吸烟状态"] = g["smoker3"].map({1: "每日", 2: "部分日", 3: "曾经", 4: "从不"})
        fig, ax = plt.subplots(figsize=(8, 5))
        sns.barplot(data=g, x="吸烟状态", y=LABEL, ax=ax, hue="吸烟状态",
                    palette="Blues_d", legend=False, errorbar=("ci", 95))
        ax.set_ylabel("共病率"); ax.set_xlabel("")
        ax.set_title(f"不同吸烟状态的共病率（95% 置信区间，抽样 n={len(g):,}）")
        p = os.path.join(OUT, "sns_smoker_rate.png")
        fig.tight_layout(); fig.savefig(p, dpi=300, bbox_inches="tight"); plt.close(fig)
        made.append(p)

    # 3) BMI 分布按是否共病（Seaborn KDE）
    if "bmi" in smp.columns:
        g = smp.dropna(subset=["bmi"])
        g = g[(g["bmi"] >= 15) & (g["bmi"] <= 50)]
        fig, ax = plt.subplots(figsize=(8, 5))
        for lab, sub, col in ((0, g[g[LABEL] == 0], "#4C78A8"), (1, g[g[LABEL] == 1], "#E45756")):
            sns.kdeplot(data=sub, x="bmi", ax=ax, fill=True, alpha=.45,
                        color=col, label="非共病" if lab == 0 else "共病")
        ax.set_xlabel("BMI"); ax.set_ylabel("概率密度")
        ax.set_title(f"BMI 分布：共病 vs 非共病（抽样 n={len(g):,}）")
        ax.legend()
        p = os.path.join(OUT, "sns_bmi_kde.png")
        fig.tight_layout(); fig.savefig(p, dpi=300, bbox_inches="tight"); plt.close(fig)
        made.append(p)

    # 4) 分年份共病率（Seaborn pointplot 展示趋势与置信带）
    if "year" in smp.columns:
        fig, ax = plt.subplots(figsize=(8, 5))
        sns.pointplot(data=smp, x="year", y=LABEL, ax=ax, color="#2E6DA4",
                      errorbar=("ci", 95), capsize=.15)
        ax.set_ylabel("共病率"); ax.set_xlabel("调查年份")
        ax.set_title("共病率年度趋势（95% 置信区间）")
        p = os.path.join(OUT, "sns_year_trend.png")
        fig.tight_layout(); fig.savefig(p, dpi=300, bbox_inches="tight"); plt.close(fig)
        made.append(p)

    # 5) 收入组 × 共病率（Seaborn boxplot -> 用 barplot 更直观）
    if "income_grp" in smp.columns:
        g = smp.dropna(subset=["income_grp"])
        fig, ax = plt.subplots(figsize=(9, 5))
        sns.barplot(data=g, x="income_grp", y=LABEL, ax=ax, hue="income_grp",
                    palette="rocket_r", legend=False, errorbar=None)
        ax.set_xlabel("收入分组（1 最低 → 5 最高）"); ax.set_ylabel("共病率")
        ax.set_title(f"共病率的收入梯度（抽样 n={len(g):,}）")
        p = os.path.join(OUT, "sns_income_gradient.png")
        fig.tight_layout(); fig.savefig(p, dpi=300, bbox_inches="tight"); plt.close(fig)
        made.append(p)

    print("\n已生成 %d 张 Seaborn 图：" % len(made))
    for p in made:
        print("  %-32s %6.0f KB" % (os.path.basename(p), os.path.getsize(p) / 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
