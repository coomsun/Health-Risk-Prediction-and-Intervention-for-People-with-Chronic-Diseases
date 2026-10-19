# -*- coding: utf-8 -*-
"""acceptance.py — 交付前最终验收（12 项硬指标）"""
import json, os, sqlite3, subprocess, sys

ROOT = r"D:\期末作业"
P = os.path.join(ROOT, "慢性病患者健康风险预测与干预")
DB = os.path.join(P, "db", "chronic_risk.db")
fails = []
def chk(cond, msg):
    print("[%s] %s" % ("PASS" if cond else "FAIL", msg))
    if not cond:
        fails.append(msg)

print("=" * 66)
print("交付前最终验收")
print("=" * 66)

for f, lo in [("大数据分析课程设计报告.docx", 500), ("项目演示PPT.pptx", 500)]:
    p = os.path.join(ROOT, f)
    sz = os.path.getsize(p) / 1024 if os.path.exists(p) else 0
    chk(lo < sz, "交付物 %-30s %8.1f KB" % (f, sz))

c = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
n = c.execute("SELECT COUNT(*) FROM fact_brfss").fetchone()[0]
u = c.execute("SELECT COUNT(DISTINCT seq_key) FROM fact_brfss").fetchone()[0]
cols = len(list(c.execute("PRAGMA table_info(fact_brfss)")))
chk(n == u and n >= 2000000, "fact_brfss = %s 行，主键唯一，%d 列" % ("{:,}".format(n), cols))

cnt = {t: c.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0] for t in
       ("dim_year", "dim_state", "dim_chronic", "agg_prevalence_year", "agg_prevalence_state",
        "agg_risk_factor", "agg_risk_stratum", "model_metrics")}
chk(cnt["agg_risk_factor"] == 45 and cnt["agg_prevalence_state"] == 2376 and cnt["model_metrics"] == 38,
    "物化表齐全：%s" % json.dumps(cnt, ensure_ascii=False))

d = dict(c.execute("SELECT risk_factor, exposure_rate FROM agg_risk_factor WHERE year=2023").fetchall())
chk(abs(d.get("heavy_drink", 0) - 0.1327) < 0.002 and abs(d.get("no_phys_activity", 0) - 0.2473) < 0.002,
    "编码归一正确：heavy_drink=%.4f（酗酒） no_phys_activity=%.4f（无运动）" %
    (d.get("heavy_drink", -1), d.get("no_phys_activity", -1)))

raw = os.path.join(P, "data", "raw")
files = sorted(f for f in os.listdir(raw) if f.endswith(".parquet"))
chk(len(files) == 5 and os.path.exists(os.path.join(raw, "MANIFEST.json"))
    and os.path.exists(os.path.join(raw, "SHA256SUMS.txt")),
    "原始数据副本 %d 个 parquet + MANIFEST + SHA256SUMS" % len(files))

fe = len([f for f in os.listdir(os.path.join(P, "artifacts", "figures")) if f.endswith(".png")])
fm = len([f for f in os.listdir(os.path.join(P, "artifacts", "figures", "model")) if f.endswith(".png")])
chk(fe >= 12 and fm >= 5, "图件 EDA %d 张 + 建模 %d 张" % (fe, fm))

mp = os.path.join(P, "artifacts", "model", "model.joblib")
fn = json.load(open(os.path.join(P, "artifacts", "model", "feature_names.json"), encoding="utf-8"))
chk(os.path.exists(mp), "model.joblib %.1f MB，特征 %d 维" % (os.path.getsize(mp) / 1024 / 1024, len(fn["features"])))

docs = sorted(os.listdir(os.path.join(P, "docs")))
chk(len(docs) >= 8, "文档 %d 份：%s" % (len(docs), "、".join(x.replace(".md", "") for x in docs)))

api9 = len([r for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")])
log = subprocess.run(["git", "log", "--oneline"], cwd=P, capture_output=True, text=True,
                     encoding="utf-8", errors="replace").stdout.strip().split("\n")
chk(len(log) >= 12, "Git 提交 %d 次（要求 ≥12）" % len(log))

meta = json.load(open(os.path.join(P, "artifacts", "model", "model_meta.json"), encoding="utf-8"))
chk(meta["metrics"]["auc_roc"] >= 0.75, "LightGBM@Set-A 测试 AUC=%.4f，CV=%.4f±%.4f" %
    (meta["metrics"]["auc_roc"], meta["cv_auc_mean"], meta["cv_auc_std"]))

ml = json.load(open(os.path.join(P, "artifacts", "metrics", "spark_mllib_metrics.json"), encoding="utf-8"))
chk(len(ml["results"]) == 2, "Spark MLlib 交叉验证：%s" %
    ", ".join("%s=%.4f" % (r["model"].split("_")[-1], r["auc_roc"]) for r in ml["results"]))

print("=" * 66)
print("结果：%d 项通过，%d 项失败" % (12 - len(fails), len(fails)))
sys.exit(1 if fails else 0)
