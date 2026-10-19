# -*- coding: utf-8 -*-
"""rebuild_aggregates.py — 从 fact_brfss 重建 dim_* 与 agg_* 物化表。

用途：当 fact_brfss 已就绪但聚合表为空/过期时，无需重跑整条建库链路（约 3 分钟），
直接由明细表重算维表与聚合表，且**不触碰** fact_brfss 与 model_metrics。
"""
import json
import os
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "db", "chronic_risk.db")
GEO = os.path.join(ROOT, "web", "vendor", "us-states.geojson")

DISEASES = [
    ("has_diabetes", "糖尿病", "Diabetes", "DIABETE4", 0),
    ("has_mi", "心肌梗死", "Myocardial infarction", "CVDINFR4", 0),
    ("has_chd", "冠心病", "Coronary heart disease", "CVDCRHD4", 0),
    ("has_stroke", "卒中", "Stroke", "CVDSTRK3", 0),
    ("has_copd", "慢阻肺", "COPD", "CHCCOPD2/CHCCOPD3", 0),
    ("has_asthma", "哮喘", "Asthma", "ASTHMA3", 0),
    ("has_kidney", "慢性肾病", "Chronic kidney disease", "CHCKDNY2", 0),
    ("has_depression", "抑郁障碍", "Depressive disorder", "ADDEPEV3", 0),
    ("multimorbidity", "共病（慢病数>=2）", "Multimorbidity", "derived: chronic_count>=2", 1),
]

# (code, 中文标签, 暴露谓词, 有效性谓词)
RISKS = [
    ("obese", "肥胖（BMI>=30）", "bmi >= 30", "bmi IS NOT NULL"),
    ("current_smoker", "现在吸烟（每日/部分日）", "smoker3 IN (1,2)", "smoker3 IS NOT NULL"),
    ("no_phys_activity", "缺乏闲暇体力活动", "phys_activity = 0", "phys_activity IS NOT NULL"),
    ("heavy_drink", "酗酒（binge，仅 2022+）", "heavy_drink = 1", "heavy_drink IS NOT NULL"),
    ("cost_barrier", "因费用而未就医", "medcost = 1", "medcost IS NOT NULL"),
    ("no_personal_doctor", "无固定就诊医生", "persdoc = 3", "persdoc IS NOT NULL"),
    ("fair_poor_health", "自评健康一般/差", "genhlth >= 4", "genhlth IS NOT NULL"),
    ("diff_walk", "行走困难", "diffwalk = 1", "diffwalk IS NOT NULL"),
    ("checkup_over_1y", "超过 1 年未体检", "checkup > 1", "checkup IS NOT NULL"),
]

AGE_LABELS = {1: "18-24", 2: "25-29", 3: "30-34", 4: "35-39", 5: "40-44", 6: "45-49",
              7: "50-54", 8: "55-59", 9: "60-64", 10: "65-69", 11: "70-74",
              12: "75-79", 13: "80+"}
INCOME_LABELS = {1: "<1.5万", 2: "1.5-2.5万", 3: "2.5-3.5万", 4: "3.5-5万", 5: ">=5万",
                 6: "缺失", 7: "未知", 8: "拒答"}
EDUCA_LABELS = {1: "未上学", 2: "小学", 3: "初中", 4: "高中/GED", 5: "大学1-3年", 6: "大学4年+"}
SMOKER_LABELS = {1: "每日吸烟", 2: "部分日吸烟", 3: "曾经吸烟", 4: "从不吸烟"}


def state_names():
    m = {}
    if os.path.exists(GEO):
        try:
            gj = json.load(open(GEO, encoding="utf-8"))
            for ft in gj.get("features", []):
                pr = ft.get("properties", {})
                fips = pr.get("fips") or ft.get("id")
                label = pr.get("label") or pr.get("name")
                if fips and label:
                    m[int(fips)] = str(label)
        except Exception:
            pass
    return m


def main() -> int:
    t0 = time.time()
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    print("fact_brfss =", "{:,}".format(cur.execute("SELECT COUNT(*) FROM fact_brfss").fetchone()[0]))

    # ---------- dim_year ----------
    cur.execute("DELETE FROM dim_year")
    cur.executemany("INSERT INTO dim_year(year, year_label, n_records) VALUES (?,?,?)",
                    [(y, str(y), n) for y, n in cur.execute(
                        "SELECT year, COUNT(*) FROM fact_brfss GROUP BY year ORDER BY year")])

    # ---------- dim_state ----------
    nm = state_names()
    cur.execute("DELETE FROM dim_state")
    rows = [(f, nm.get(f, "FIPS %02d" % f), "", "", n) for f, n in cur.execute(
        "SELECT state_fips, COUNT(*) FROM fact_brfss GROUP BY state_fips ORDER BY state_fips")]
    cur.executemany("INSERT INTO dim_state(state_fips, state_name, state_abbr, region, n_records) VALUES (?,?,?,?,?)", rows)

    # ---------- dim_age_group / income / education ----------
    cur.execute("DELETE FROM dim_age_group")
    cur.executemany("INSERT INTO dim_age_group(age_grp, age_label) VALUES (?,?)",
                    [(k, v) for k, v in sorted(AGE_LABELS.items())])
    cur.execute("DELETE FROM dim_income_group")
    cur.executemany("INSERT INTO dim_income_group(income_grp, income_label) VALUES (?,?)",
                    [(k, v) for k, v in sorted(INCOME_LABELS.items())])
    cur.execute("DELETE FROM dim_education")
    cur.executemany("INSERT INTO dim_education(educa, educa_label) VALUES (?,?)",
                    [(k, v) for k, v in sorted(EDUCA_LABELS.items())])

    # ---------- dim_chronic ----------
    cur.execute("DELETE FROM dim_chronic")
    cur.executemany("INSERT INTO dim_chronic(disease_code, disease_name_cn, disease_name_en, source_var, is_primary_label) "
                    "VALUES (?,?,?,?,?)", DISEASES)

    # ---------- agg_prevalence_year ----------
    cur.execute("DELETE FROM agg_prevalence_year")
    for code, cn_name, _en, _src, _p in DISEASES:
        cur.execute("""
            INSERT INTO agg_prevalence_year(year, disease_code, disease_name_cn, n_valid, n_positive, prevalence)
            SELECT year, ?, ?, COUNT({c}), SUM({c}), 1.0*SUM({c})/COUNT({c})
            FROM fact_brfss WHERE {c} IS NOT NULL GROUP BY year
        """.format(c=code), (code, cn_name))

    # ---------- agg_prevalence_state ----------
    cur.execute("DELETE FROM agg_prevalence_state")
    for code, cn_name, _en, _src, _p in DISEASES:
        cur.execute("""
            INSERT INTO agg_prevalence_state(year, state_fips, disease_code, n_valid, n_positive, prevalence)
            SELECT year, state_fips, ?, COUNT({c}), SUM({c}), 1.0*SUM({c})/COUNT({c})
            FROM fact_brfss WHERE {c} IS NOT NULL GROUP BY year, state_fips
        """.format(c=code), (code,))

    # ---------- agg_risk_factor ----------
    cur.execute("DELETE FROM agg_risk_factor")
    for code, cn_label, pred, valid in RISKS:
        cur.execute("""
            INSERT INTO agg_risk_factor(year, risk_factor, risk_label_cn, level_label, n_valid, n_positive, exposure_rate)
            SELECT year, ?, ?, '暴露', COUNT(*), SUM(CASE WHEN {p} THEN 1 ELSE 0 END),
                   CASE WHEN COUNT(*) > 0 THEN 1.0*SUM(CASE WHEN {p} THEN 1 ELSE 0 END)/COUNT(*) ELSE NULL END
            FROM fact_brfss WHERE {v} GROUP BY year
        """.format(p=pred, v=valid), (code, cn_label))

    # 补齐缺失年份的占位行：保证每年恒为 9 项（heavy_drink 2019-2021 全缺失）
    for code, cn_label, _p, _v in RISKS:
        for (y,) in cur.execute("SELECT year FROM dim_year ORDER BY year").fetchall():
            cur.execute("INSERT OR IGNORE INTO agg_risk_factor"
                        "(year, risk_factor, risk_label_cn, level_label, n_valid, n_positive, exposure_rate) "
                        "VALUES (?,?,?,?,0,0,NULL)", (y, code, cn_label, "暴露"))

    # ---------- agg_risk_stratum ----------
    cur.execute("DELETE FROM agg_risk_stratum")
    defs = [
        ("chronic_count", "chronic_count", "慢病种数"),
        ("age_grp", "age_grp", "年龄组"),
        ("sex", "sex", "性别"),
        ("smoker3", "smoker3", "吸烟状态"),
        ("bmi_class", "CASE WHEN bmi IS NULL THEN 0 WHEN bmi < 18.5 THEN 1 WHEN bmi < 25 THEN 2 "
                        "WHEN bmi < 30 THEN 3 ELSE 4 END", "BMI 分级"),
    ]
    lab = {
        "age_grp": AGE_LABELS, "sex": {1: "男", 2: "女"}, "smoker3": SMOKER_LABELS,
        "bmi_class": {0: "未知", 1: "偏瘦 <18.5", 2: "正常 18.5-25", 3: "超重 25-30", 4: "肥胖 >=30"},
    }
    for d in list(lab):
        lab[d] = dict(lab[d]); lab[d].setdefault(-1, "未知")
    for dim, expr, _n in defs:
        cur.execute("""
            INSERT INTO agg_risk_stratum(dimension, stratum_code, stratum_label, n, n_multimorbidity, multimorbidity_rate)
            SELECT ?, CAST(COALESCE(s, -1) AS INTEGER), NULL, COUNT(*), SUM(multimorbidity), 1.0*SUM(multimorbidity)/COUNT(*)
            FROM (SELECT {e} AS s, multimorbidity FROM fact_brfss) GROUP BY COALESCE(s, -1)
        """.format(e=expr), (dim,))
        for code, label in lab.get(dim, {}).items():
            cur.execute("UPDATE agg_risk_stratum SET stratum_label=? WHERE dimension=? AND stratum_code=?",
                        (label, dim, code))

    # ---------- audit ----------
    n_agg = {t: cur.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
             for t in ("agg_prevalence_year", "agg_prevalence_state", "agg_risk_factor", "agg_risk_stratum")}
    cur.execute("INSERT INTO audit_pipeline(run_id, step, started_at, finished_at, elapsed_sec, rows_in, rows_out, detail) "
                "VALUES (?,?,?,?,?,?,?,?)",
                ("agg-rebuild", "rebuild_aggregates", time.strftime("%Y-%m-%dT%H:%M:%S"),
                 time.strftime("%Y-%m-%dT%H:%M:%S"), round(time.time() - t0, 1), None,
                 sum(n_agg.values()), json.dumps(n_agg, ensure_ascii=False)))
    conn.commit()
    for k, v in n_agg.items():
        print("  %-24s %s" % (k, "{:,}".format(v)))
    print("dim_year=%d dim_state=%d dim_chronic=%d" % (
        cur.execute("SELECT COUNT(*) FROM dim_year").fetchone()[0],
        cur.execute("SELECT COUNT(*) FROM dim_state").fetchone()[0],
        cur.execute("SELECT COUNT(*) FROM dim_chronic").fetchone()[0]))
    conn.close()
    print("DONE in %.1fs" % (time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
