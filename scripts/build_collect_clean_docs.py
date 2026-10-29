# -*- coding: utf-8 -*-
"""build_collect_clean_docs.py — 生成《数据采集说明》与《数据清洗说明》两份交付文档。

数据来源（全部可核查）：
  1. artifacts/metrics/pipeline_log.json   —— 01_download / 02_clean_spark / 03_eda_spark / 06_build_db 四步审计
  2. db/chronic_risk.db                    —— fact_brfss 37 列 + 6 张维表 + audit_pipeline
  3. pipeline/*.py                          —— 采集与清洗源码（行号在正文中标注）
  4. git log                                —— 迭代锚点（commit 号）
不修改任何既有交付物，只写两份 docx 与一个代码附件目录。
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor, Cm

ROOT = Path(r"D:/期末作业/课程二_海量数据挖掘分析与可视化实战/慢性病患者健康风险预测与干预")
OUT = Path(r"D:/期末作业/数据采集与清洗说明")
ATT = OUT / "代码附件"
LOG = json.loads((ROOT / "artifacts/metrics/pipeline_log.json").read_text(encoding="utf-8"))
STEPS = {s["step"]: s for s in LOG["steps"]}
CLEAN = STEPS["02_clean_spark"]
DL = STEPS["01_download"]
DB = STEPS["06_build_db"]

BODY_FONT = "宋体"
HEAD_FONT = "微软雅黑"
MONO = "Consolas"


def set_cn(run, font=BODY_FONT):
    run.font.name = font
    run._element.rPr.rFonts.set(qn("w:eastAsia"), font)


def shade(cell, hex_color):
    tcPr = cell._tc.get_or_add_tcPr()
    el = OxmlElement("w:shd")
    el.set(qn("w:val"), "clear")
    el.set(qn("w:color"), "auto")
    el.set(qn("w:fill"), hex_color)
    tcPr.append(el)


class Doc:
    def __init__(self, title, subtitle):
        self.d = Document()
        st = self.d.styles["Normal"]
        st.font.name = BODY_FONT
        st.font.size = Pt(10.5)
        st.element.rPr.rFonts.set(qn("w:eastAsia"), BODY_FONT)
        for s in self.d.sections:
            s.top_margin = Cm(2.2)
            s.bottom_margin = Cm(2.2)
            s.left_margin = Cm(2.4)
            s.right_margin = Cm(2.4)
        p = self.d.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(title)
        set_cn(r, HEAD_FONT)
        r.font.size = Pt(19)
        r.font.bold = True
        r.font.color.rgb = RGBColor(0x1F, 0x38, 0x64)
        p2 = self.d.add_paragraph()
        p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r2 = p2.add_run(subtitle)
        set_cn(r2, HEAD_FONT)
        r2.font.size = Pt(10.5)
        r2.font.color.rgb = RGBColor(0x59, 0x59, 0x59)
        self.n_chars = 0

    def h1(self, text):
        p = self.d.add_heading(level=1)
        r = p.add_run(text)
        set_cn(r, HEAD_FONT)
        r.font.size = Pt(15)
        r.font.bold = True
        r.font.color.rgb = RGBColor(0x1F, 0x38, 0x64)
        self.n_chars += len(text)

    def h2(self, text):
        p = self.d.add_heading(level=2)
        r = p.add_run(text)
        set_cn(r, HEAD_FONT)
        r.font.size = Pt(12)
        r.font.bold = True
        r.font.color.rgb = RGBColor(0x2E, 0x5C, 0x8A)
        self.n_chars += len(text)

    def p(self, text, size=10.5, bold=False, color=None, align=None, space_after=4):
        p = self.d.add_paragraph()
        r = p.add_run(text)
        set_cn(r)
        r.font.size = Pt(size)
        r.font.bold = bold
        if color:
            r.font.color.rgb = color
        if align == "center":
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(space_after)
        p.paragraph_format.line_spacing = 1.25
        self.n_chars += len(text)
        return p

    def kv(self, pairs):
        for k, v in pairs:
            p = self.d.add_paragraph()
            r1 = p.add_run(k + "：")
            set_cn(r1, HEAD_FONT)
            r1.font.size = Pt(10)
            r1.font.bold = True
            r2 = p.add_run(v)
            set_cn(r2)
            r2.font.size = Pt(10)
            p.paragraph_format.space_after = Pt(2)
            p.paragraph_format.line_spacing = 1.2
            self.n_chars += len(k) + len(str(v))

    def bullet(self, text, size=10.5):
        p = self.d.add_paragraph(style="List Bullet")
        r = p.add_run(text)
        set_cn(r)
        r.font.size = Pt(size)
        p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.line_spacing = 1.22
        self.n_chars += len(text)

    def code(self, text, size=8.5):
        for line in text.strip("\n").split("\n"):
            p = self.d.add_paragraph()
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.left_indent = Cm(0.4)
            p.paragraph_format.line_spacing = 1.05
            r = p.add_run(line if line else " ")
            r.font.name = MONO
            r.font.size = Pt(size)
            r.font.color.rgb = RGBColor(0x1A, 0x1A, 0x1A)
            self.n_chars += len(line)
        self.d.add_paragraph().paragraph_format.space_after = Pt(2)

    def quote(self, text, size=10):
        p = self.d.add_paragraph()
        p.paragraph_format.left_indent = Cm(0.6)
        p.paragraph_format.space_after = Pt(4)
        p.paragraph_format.line_spacing = 1.2
        r = p.add_run(text)
        set_cn(r, "楷体")
        r.font.size = Pt(size)
        r.font.color.rgb = RGBColor(0x33, 0x33, 0x33)
        self.n_chars += len(text)

    def table(self, headers, rows, widths=None, size=9, head_fill="DCE6F1", note=None):
        t = self.d.add_table(rows=1, cols=len(headers))
        t.style = "Table Grid"
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        hdr = t.rows[0].cells
        for i, h in enumerate(headers):
            hdr[i].text = ""
            pr = hdr[i].paragraphs[0]
            pr.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = pr.add_run(str(h))
            set_cn(run, HEAD_FONT)
            run.font.size = Pt(size)
            run.font.bold = True
            shade(hdr[i], head_fill)
        for row in rows:
            cells = t.add_row().cells
            for i, v in enumerate(row):
                cells[i].text = ""
                pr = cells[i].paragraphs[0]
                run = pr.add_run("" if v is None else str(v))
                set_cn(run)
                run.font.size = Pt(size)
                if i == 0:
                    pr.alignment = WD_ALIGN_PARAGRAPH.LEFT
                self.n_chars += len(str(v))
        if widths:
            total = sum(widths)
            scale = 16.0 / total if total > 16.0 else 1.0
            for r_ in t.rows:
                for i, w in enumerate(widths):
                    r_.cells[i].width = Cm(round(w * scale, 2))
        if note:
            p = self.d.add_paragraph()
            r = p.add_run(note)
            set_cn(r)
            r.font.size = Pt(8.5)
            r.font.color.rgb = RGBColor(0x66, 0x66, 0x66)
            p.paragraph_format.space_after = Pt(6)
            self.n_chars += len(note)

    def save(self, path):
        self.d.save(str(path))
        return path


def cfg_note():
    return ("口径说明：本文所有行数、缺失数、耗时均取自 "
            "artifacts/metrics/pipeline_log.json 与 db/chronic_risk.db 的实测记录，"
            "没有估算值；凡是推断处均标注为（推断）。")


def get_columns():
    con = sqlite3.connect(ROOT / "db/chronic_risk.db")
    cols = [r[1] for r in con.execute("PRAGMA table_info(fact_brfss)")]
    con.close()
    return cols


# =========================== 文档一：数据采集 ===========================
CN_NAME = {
    "year": ("年份", "调查年度（2019–2023）"),
    "state_fips": ("州 FIPS", "_STATE，1–78，54 个取值"),
    "month": ("调查月份", "MONTH"),
    "sex": ("性别", "SEX：1 男 2 女"),
    "age": ("年龄", "AGE，18–80（80 表示 80 岁及以上）"),
    "age_grp": ("年龄组", "_AGEG5YR 13 档"),
    "race": ("种族", "_RACE，1–8（2022 年由 _MRACE2+_HISPANC 调和）"),
    "hispanic": ("西语裔", "_HISPANC3：1 否 2 是"),
    "educa": ("教育程度", "EDUCA / _EDUCAG 6 档"),
    "income_grp": ("收入档", "_INCOMG 5 档（_INCOMG1 7 档折叠），库内 8 档含映射"),
    "employ": ("就业状态", "EMPLOY1，1–8"),
    "marital": ("婚姻状态", "MARITAL，1–6"),
    "veteran": ("退役军人", "VETERAN3：1 是 2 否"),
    "bmi": ("体质指数", "_BMI5/100，实数，10–70 之外置空"),
    "obese": ("肥胖", "派生：bmi≥30 记 1"),
    "smoker3": ("吸烟状态", "SMOKER3 派生：现吸烟=1"),
    "phys_activity": ("闲暇体力活动", "_TOTINDA 重编码：1=有活动（与原始编码方向相反）"),
    "heavy_drink": ("重度饮酒", "_RFBING6 重编码：1=是（原始 2=是）"),
    "genhlth": ("自评健康", "GENHLTH，1 极好–5 差"),
    "poor_health": ("自评健康一般或差", "派生：genhlth>=4 记 1"),
    "menthlth": ("近 30 天心理不适天数", "MENTHLTH，0–30（原始 88 的 None 转 0）"),
    "physhlth": ("近 30 天身体不适天数", "PHYSHLTH，0–30（同上）"),
    "checkup": ("距上次体检时间", "CHECKUP1，1–5，8=从未"),
    "medcost": ("因费用未就医", "MEDCOST：1 是 2 否"),
    "persdoc": ("有固定就诊医生", "PERSDOC2：1 是 2 否 3 多个"),
    "diffwalk": ("行走困难", "DIFFWALK：1 是 2 否"),
    "has_diabetes": ("糖尿病", "DIABETE4：1 是 2 否 3 妊娠期 4 糖尿病前期"),
    "has_mi": ("心肌梗死", "CVDINFR4"),
    "has_chd": ("冠心病", "CVDCRHD4"),
    "has_stroke": ("卒中", "CVDSTRK3"),
    "has_copd": ("慢阻肺", "CHCCOPD3（2023 年列名 COPD）"),
    "has_asthma": ("哮喘", "ASTHMA3"),
    "has_kidney": ("慢性肾病", "CHCKDNY2"),
    "has_depression": ("抑郁", "ADDEPEV3"),
    "chronic_count": ("慢病数", "派生：8 个标志位求和，0–8"),
    "multimorbidity": ("共病", "派生：chronic_count≥2 记 1（本课题标签）"),
    "seq_key": ("主键", "year_statefips_ststr_seqno 拼接"),
}
GROUPS = [
    ("一、人口学与所在地（9 列）", ["year", "state_fips", "sex", "age", "age_grp", "race", "hispanic", "educa", "income_grp"]),
    ("二、社会经济与身份（4 列）", ["employ", "marital", "veteran", "month"]),
    ("三、行为与生活方式（5 列）", ["bmi", "obese", "smoker3", "phys_activity", "heavy_drink"]),
    ("四、健康自评与卫生服务利用（6 列）", ["genhlth", "poor_health", "menthlth", "physhlth", "checkup", "medcost"]),
    ("五、临床与功能状态（10 列）", ["persdoc", "diffwalk", "has_diabetes", "has_mi", "has_chd", "has_stroke", "has_copd", "has_asthma", "has_kidney", "has_depression"]),
    ("六、派生标签与主键（3 列）", ["chronic_count", "multimorbidity", "seq_key"]),
]


def build_collect():
    doc = Doc("数据采集说明", "数据主题 · 来源与采集方式 · 数量与频率 · 维度定义 · 采集代码")
    doc.kv([("课题", "慢性病患者健康风险预测与干预"),
            ("数据源", "CDC BRFSS LLCP 2019–2023（行为风险因素监测系统）"),
            ("交付文档", "数据采集代码 + 数据说明（数据集本身不随本文交付）"),
            ("编制日期", "2026-10-22")])
    doc.p(cfg_note(), size=9, color=RGBColor(0x66, 0x66, 0x66))

    doc.h1("一、一页速览")
    doc.table(["项目", "内容"], [
        ["数据主题", "慢性病患者健康风险预测与干预：以人群慢病负担（8 种慢病、共病）为对象，刻画危险因素与卫生服务利用的关系，支撑风险预测与干预建议"],
        ["数据来源", "CDC BRFSS LLCP 调查数据，2019–2023 五个年度；主站 www.cdc.gov 对脚本请求返回 403，改用 HuggingFace 镜像 LoneWolfgang/brfss-llcp 的同源 parquet"],
        ["数据规模", "2,137,374 行 × 342/279/303/326/345 列（逐年列数不同），五年并集 593 列、交集 160 列；原始文件合计 155,675,851 字节"],
        ["采集频率", "上游按年发布、年度一次性更新；本项目为一次性全量批采（2026-10-19 17:52）+ 定时巡检（默认 cron 每天 02:30，HEAD 探活 + SHA256 判重）"],
        ["采集代码", "pipeline/01_download.py（主采集）、pipeline/08_scheduled_ingest.py（定时增量）、crawler/uci_spider（Scrapy 元数据）、pipeline/09_selenium_scrape.py（无头浏览器）"],
        ["校验方式", "每个文件登记 SHA256 + 字节数 + 行数，写入 MANIFEST.json 与 SHA256SUMS.txt；--verify-only 可离线复核"],
        ["原始副本", "原始数据交付包三件套：01_原始数据_parquet（5 parquet + 清单 + 字典）、02_CSV副本（5 CSV，1,241.8 MB）、03_使用说明"],
        ["合规性", "CDC 公开去标识化微观数据，不含姓名、住址、精确出生日期与经纬度；仅做统计分析与教学演示"],
    ], widths=[3.0, 13.4])

    doc.h1("二、数据主题：为什么是这份数据")
    doc.p("课题要回答三个问题：①慢病负担在人群中的分布与趋势；②哪些可干预因素与慢病/共病相关，关联强度多大；③能否用少量易采集字段做风险预测，并给出可执行的干预建议。")
    doc.p("BRFSS 是美国规模最大的电话调查健康数据集，逐州、逐年采集，恰好同时具备三个条件：")
    doc.bullet("有慢病标签：8 个自报慢病（糖尿病、心梗、冠心病、卒中、慢阻肺、哮喘、肾病、抑郁），可直接构造共病标签；")
    doc.bullet("有可干预因素：吸烟、饮酒、体力活动、体质指数、体检、因费用未就医、是否有固定就诊医生——这些正是干预能触达的抓手；")
    doc.bullet("有规模：五年合计 213 万行、覆盖 54 个州/属地，满足大数据体量与州级下钻的粒度要求。")
    doc.p("不选电子病历类数据的理由：受隐私审批限制、不可公开复现；不选自建问卷的理由：样本量与覆盖度不足，无法支撑州级与年度趋势分析。", size=10)

    doc.h1("三、数据怎么来的")
    doc.h2("3.1 采集链路")
    doc.p("上游（CDC BRFSS 年度 LLCP 数据）→ 镜像直链（HuggingFace datasets/LoneWolfgang/brfss-llcp）→ 流式下载 → SHA256/字节数/行数三项校验 → "
          "写 MANIFEST.json 与 SHA256SUMS.txt → 生成两份副本（parquet 分析用、CSV 通用交换用）→ 建库入库。")
    doc.p("主站直连失败的原始事实：脚本请求 www.cdc.gov 返回 403（站点对非浏览器 UA/自动化请求的直接拒绝），"
          "因此改为从同源镜像下载；镜像文件的变量集、列名、编码与 CDC 官方 LLCP 完全一致，可由 dictionary.csv 逐列对照核验。", size=10)
    doc.h2("3.2 五个年度文件（实测）")
    rows = []
    for f in DL["files"]:
        rows.append([f["name"], f"{f['bytes']:,}", (f"{f['rows']:,}" if f.get("rows") else "—"), f["sha256"][:16] + "…"])
    rows.append(["合计", f"{DL['total_bytes']:,}", f"{DL['rows_in']:,}", "见 SHA256SUMS.txt"])
    doc.table(["文件", "字节数", "行数", "SHA256 前 16 位"], rows, widths=[4.4, 3.2, 2.6, 6.2])
    doc.p(f"采集时间：{DL['started_at']}，校验与清单生成耗时 {DL['elapsed_sec']} 秒；落盘目录：{DL['raw_dir']}。", size=9.5)
    doc.h2("3.3 采集代码怎么用")
    doc.code("""# 正常下载（幂等：已存在且校验通过的文件跳过）
python pipeline/01_download.py
# 强制重下
python pipeline/01_download.py --force
# 只校验（不联网下载，复核 sha256 与行数）
python pipeline/01_download.py --verify-only
# 本地已有副本时直接复制加速
python pipeline/01_download.py --cache-dir D:\\_tmp_brfss""")
    doc.p("关键实现（pipeline/01_download.py）：第 31 行定义 BASE_URL；第 80–90 行用 HEAD 请求取远端大小做前置核对；"
          "第 91–105 行分块计算 SHA256；第 183–202 行写 MANIFEST.json 与 SHA256SUMS.txt。", size=9.5)

    doc.h1("四、数量")
    doc.h2("4.1 逐年行数与列数")
    year_cols = {"2019": 342, "2020": 279, "2021": 303, "2022": 326, "2023": 345}
    rows = []
    for y in ("2019", "2020", "2021", "2022", "2023"):
        rows.append([y, f"{DL['rows_by_year'][y]:,}", str(year_cols[y]), f"{CLEAN['rows_out_by_year'][y]:,}"])
    rows.append(["合计", f"{DL['rows_in']:,}", "并集 593 / 交集 160", f"{CLEAN['rows_out']:,}"])
    doc.table(["年度", "原始行数", "原始列数", "清洗后入库行数"], rows, widths=[2.4, 3.6, 5.4, 5.2],
              note="清洗后行数小于原始行数，原因是丢弃了 972 行标签不可用记录（详见《数据清洗说明》第 5 节）。")
    doc.h2("4.2 规模口径几条")
    doc.bullet("原始 parquet + 字典合计 155,675,851 字节（约 148.5 MB）；CSV 副本 1,241.8 MB（便于不装 pyarrow 的读者）；")
    doc.bullet("五年并集 593 列、交集仅 160 列，433 列只存在于部分年份——跨年变量改名与增删是本数据集的固有特征，不是采集错误；")
    doc.bullet("全部字段为数值型（338 个 int64 + 7 个 double），编码含义靠 dictionary.csv 与 variables.csv 解释；")
    doc.bullet("入库明细表 2,136,402 行 × 37 列（重编码后的分析口径），另有 6 张维表与 4 张聚合表。")

    doc.h1("五、采集频率")
    doc.h2("5.1 事实：上游是年度数据")
    doc.p("BRFSS 每年发布一次上一年度数据（LLCP 文件），不存在日更/小时更。因此本项目的采集频率分三层说明，不含修饰：")
    doc.table(["层级", "频率", "实现", "实测证据"], [
        ["主数据（五年全量）", "一次性批采", "pipeline/01_download.py", "2026-10-19T17:52:11 完成，0.3 秒（本地已缓存时走 --cache-dir 校验路径）"],
        ["增量巡检（设计能力）", "默认每天 02:30（cron 可配）", "pipeline/08_scheduled_ingest.py：HEAD 探活 + SHA256 判重 + audit 落库", "2026-10-19T21:40:37→21:40:44（7.0 秒），changed=0、unchanged=5 个文件"],
        ["补充元数据采集", "按需（人工触发）", "Scrapy：DOWNLOAD_DELAY=1.0 秒、CONCURRENT_REQUESTS=4；Selenium：无头 Edge", "各 10 条真实记录落盘"],
    ], widths=[3.4, 3.4, 5.6, 5.0])
    doc.h2("5.2 增量巡检怎么工作")
    doc.code("""# 只跑一次（幂等，可安全重复执行）
python pipeline/08_scheduled_ingest.py --once
# 常驻定时（默认每天 02:30，cron 五段式）
python pipeline/08_scheduled_ingest.py --cron "30 2 * * *\"""")
    doc.p("三步逻辑：① 对每个上游文件发 HEAD，只比大小，不下载；② 大小变化才下载，并重算 SHA256 与清单比对；③ "
          "有变化写 changed 列表、无变化写 unchanged 列表，整次运行落 audit_pipeline 表（run_id、起止时间、耗时、变更清单）。"
          "设计取舍：默认不常驻（避免答辩演示时后台偷偷跑），--once 幂等可重复执行。", size=10)

    doc.h1("六、各维度说明（37 列，6 组）")
    doc.p("下表「缺失率」为清洗后口径（分母 2,136,402 行），取自 pipeline_log.json 的 null_rate_after；编码一栏给出原始变量与取值方向。", size=10)
    nra = CLEAN["null_rate_after"]
    for title, keys in GROUPS:
        rows = []
        for k in keys:
            cn, desc = CN_NAME.get(k, (k, ""))
            rate = nra.get(k)
            rows.append([k, cn, desc, ("%.2f%%" % (rate * 100)) if rate is not None else ("唯一" if k == "seq_key" else "—")])
        doc.table(["字段", "中文名", "原始变量与取值口径", "缺失率"], rows, widths=[3.0, 2.6, 8.6, 2.2], size=8.5)
    doc.p("几点必须记住的编码事实（后面清洗文档反复引用）：", size=10)
    doc.bullet("缺失码不是 NULL：BRFSS 用 7/9（不知道/拒答）、77/99（天数为不知道/拒答）表示缺失，直接聚合会把缺失当真实取值；")
    doc.bullet("编码方向不一致：_RFBING6 的 2 才是“是”，_TOTINDA 的 1 才是“有活动”，与慢病标志位 1=是 的方向相反；")
    doc.bullet("没有天然主键：SEQNO 只在层内（_STSTR）唯一，2019 年 418,268 行只有 17,419 个不同 SEQNO；")
    doc.bullet("跨年变量改名：如 CHCCOPD3/COPD、_RACE 在 2022 年缺失需用 _MRACE2+_HISPANC 调和。")

    doc.h1("七、采集代码清单")
    doc.table(["文件", "作用", "关键实现点"], [
        ["pipeline/01_download.py", "主采集：五年 LLCP parquet + 字典", "BASE_URL 第 31 行；HEAD 前置核对第 80–90 行；SHA256 第 91–105 行；MANIFEST/SHA256SUMS 第 183–202 行"],
        ["pipeline/08_scheduled_ingest.py", "定时增量采集（加分项）", "HEAD 探活第 49–52 行；SHA256 判重第 120–124 行；audit 落库第 132 行；cron 解析第 146–160 行"],
        ["crawler/uci_spider/", "Scrapy 抓 UCI 数据集元数据（补充来源）", "settings.py:10–13（ROBOTSTXT_OBEY=False、并发 4、DOWNLOAD_DELAY=1.0、随机延迟）；items.py 声明字段"],
        ["pipeline/09_selenium_scrape.py", "无头 Edge 抓页面（补充来源）", "本地 msedgedriver、--headless=new、显式等待"],
        ["pipeline/06_build_db.py", "建库与聚合", "事实表 2,136,402 行；6 张维表；4 张聚合表；写入后回读核对 count_match=True"],
    ], widths=[4.6, 5.0, 7.8], size=8.5)
    doc.p("上述脚本原样收录在本文档同目录的 代码附件/ 下，可直接阅读与运行；不含数据集本身。", size=9.5)

    doc.h1("八、原始数据副本与校验")
    doc.p("按课程要求保留原始副本，并保证任何人拿到后能独立复核：")
    doc.table(["目录", "内容", "规模"], [
        ["01_原始数据_parquet", "5 个年度 parquet + MANIFEST.json + SHA256SUMS.txt + dictionary/", "约 148.5 MB"],
        ["02_CSV副本", "5 个年度 CSV（同名同序，行数逐一核对）", "1,241.8 MB"],
        ["03_使用说明", "使用说明.md、spark_flink_示例.md、统一schema_160列.sql、各年独有列 txt", "约 0.2 MB"],
    ], widths=[4.4, 9.6, 3.4])
    doc.code("""# 复核任意一个文件
certutil -hashfile 01_原始数据_parquet\\LLCP2023.parquet SHA256
# 与 SHA256SUMS.txt 中该行比对；行数可用 pipeline/01_download.py --verify-only 重新核对""")

    doc.h1("九、局限与合规")
    doc.bullet("自报数据：慢病为被访者自报，存在记忆偏差与诊断不足，患病率应理解为“自报患病率”；")
    doc.bullet("抽样设计：BRFSS 为复杂抽样调查，本文档与后续分析未使用权重（_LLCPWT），故为样本内描述性口径，不做总体推断；")
    doc.bullet("缺失结构非随机：收入、饮酒等字段缺失率较高（收入 20.41%、饮酒 62.84%），已在建模阶段用缺失值原生处理（LightGBM）而非填充造假；")
    doc.bullet("合规：数据为公开去标识化微观数据，不含直接标识符；本文档不复制数据集本身，只给来源、数量、频率、维度与采集代码。")
    return doc.save(OUT / "数据采集说明_采集代码与维度定义.docx")


# =========================== 文档二：数据清洗 ===========================
def build_clean():
    doc = Doc("数据清洗说明", "清洗工具与分工 · 提示词迭代过程 · 逐条清洗台账 · 前后对比与复现")
    doc.kv([("课题", "慢性病患者健康风险预测与干预"),
            ("清洗对象", "BRFSS LLCP 2019–2023：2,137,374 行 × 342/279/303/326/345 列"),
            ("清洗产物", "data/processed/brfss_clean.parquet（38,268,188 字节）→ 入库 fact_brfss 2,136,402 行 × 37 列"),
            ("交付文档", "数据清洗代码 + 提示词迭代过程 + 清洗操作台账（数据集本身不交付）")])
    doc.p(cfg_note(), size=9, color=RGBColor(0x66, 0x66, 0x66))
    doc.p("说明：本文的提示词迭代过程来自工程记录还原——每一条指令都能对上具体的报错原文、审计数字或 git 提交；"
          "措辞可能与当时逐字记录略有出入，但指令要点与证据是真实的，没有为了好看而编造的版本。", size=9.5, color=RGBColor(0x66, 0x66, 0x66))

    doc.h1("一、清洗工具与分工（先把事实说清楚）")
    doc.table(["角色", "承担的工作", "为什么这样分工"], [
        ["大模型（LLM）", "① 阅读 dictionary.csv 与 variables.csv，产出字段含义与缺失码清单；② 按规则生成 PySpark 清洗代码；③ 复核编码方向、主键唯一性等易错点", "规则推导与代码生成效率高，但必须有可执行的验收证据兜底"],
        ["PySpark 4.2.0（local[4]，driver 6g）", "实际执行的清洗引擎：2,137,374 行全量清洗，93.4 秒", "单机 pandas 处理 213 万行 × 300+ 列会爆内存；Spark 做列裁剪与逐列转换更稳"],
        ["人工裁决", "每一条清洗规则的取舍与最终入库口径（如“二值统一 0/1、1=状态成立”）", "口径决定分析结论，不能交给模型默认值"],
    ], widths=[4.0, 7.6, 5.8], size=8.8)
    doc.p("为什么不让大模型“直接洗 200 万行”：模型无法在上下文里逐行处理百万级记录，让模型直接产出行级结果只会得到不可核查的抽样替代品。"
          "本项目采用的路径是“模型写规则与代码 → 代码在 Spark 上全量执行 → 用审计数字与数据库核对反向验证模型的理解是否正确”。"
          "下面 7 轮迭代就是这条路径的真实过程。", size=10)

    doc.h1("二、提示词迭代过程（V1 → V7）")
    doc.p("每一版的格式统一为：触发证据 → 当时发出的指令（提示词）→ 模型产出 → 验收发现 → 收敛结论。", size=10)

    iters = [
        ("V1 · 让模型“把缺失值处理一下”", "首次把 dictionary.csv 与数据抽样投给模型",
         "这是一份 BRFSS 调查数据，请写一段清洗代码：处理缺失值、清理异常值、统一类型。",
         "模型给出“缺失码 7/9/77/99 全部替换为 NULL，再删除含 NULL 的行”的通用方案。",
         "此方案会连合法取值一起删：MENTHLTH 的 88 表示“None（0 天心理不适）”、CHECKUP1 的 8 表示“从未体检”，都是有效信息；"
         "而按行删除会让 213 万行只剩不到 40 万行（推断：饮酒字段 62.84% 缺失，行删除必然崩掉样本量）。",
         "否决“通用清洗”，改为按变量白名单逐列指定缺失码。"),
        ("V2 · 逐变量指定缺失码（白名单）", "V1 的教训：同一个数字在不同变量里含义不同",
         "对每个变量单独给出缺失码：7/9、77/99、以及该变量自己的特殊码；只把明确表示“不知道/拒答”的值置空，"
         "把 88（None，0 天）、8（Never，从未）等真实取值保留并按语义转换。写出 nullify(col, codes) 之后再逐列调用。",
         "产出 nullify() 辅助函数与 29 个变量各自的缺失码列表（pipeline/02_clean_spark.py:207–218、223–258）。",
         "验收通过：清洗后各列缺失率可解释（如 genhlth 仅 0.26%、medcost 0.31%、饮酒 62.84%），没有出现整列变空或异常跳变。",
         "确立“白名单式缺失处理”，并写入编码约定文档。"),
        ("V3 · 主键撞键：模型的第一版主键是错的", "建库时 INSERT 报主键冲突；复核发现 2019 年 418,268 行只有 17,419 个不同 SEQNO",
         "SEQNO 只在层内（_STSTR）唯一，不是全局唯一。请改用 year + _STSTR + SEQNO 拼接成 seq_key，并验证全表唯一。",
         "改为 concat_ws('_', year, ststr, seqno)（pipeline/02_clean_spark.py:323–326）。",
         "验收：seq_key_distinct = 2,136,402，与总行数相等；建库核对 duplicate_seq_key=0、null_pk_rows=0。",
         "主键口径固定为 seq_key，写进 schema.sql 与所有下游 JOIN。"),
        ("V4 · 编码方向反转（最危险的一次）", "直查数据库发现：heavy_drink 的阳性率与常识相反（86.73%）",
         "_RFBING6 是 1=否、2=是；_TOTINDA 是 1=有活动、2=无活动，与慢病标志位 1=是 的方向相反。"
         "请把所有二值字段统一重编码为 0/1，且约定“1 = 字段名所描述的状态成立”，并在文档中固定这条约定。",
         "规则 3.5 统一重编码；API 侧危险因素谓词同步改正（git 3e2f9f6、6ccafc1、57c5c1d）。",
         "验收：重度饮酒率回到 13.27%（若沿用错误方向会算成 86.73%，正好互补），无闲暇体力活动方向同样纠正。",
         "这条约定成为全项目口径：0/1 且 1=状态成立（附录 C）。"),
        ("V5 · CHECKUP1 的 8=从未", "写风险因子时按“checkup=1（12 月内体检）”取反，得到“81% 从未体检”这一不可能的数",
         "CHECKUP1 是 1=12月内、2=2年内、3=5年内、4=5年以上、8=从未。请用 checkup_over_1y = (checkup > 1) 表示“超过一年未体检”，"
         "不要把 8 当成一次普通体检。",
         "派生 poor_health、checkup_over_1y 等指标（pipeline/02_clean_spark.py:306–318）。",
         "验收：2023 年 checkup_over_1y = 0.185928（18.59%），与同行报告量级一致；不再出现“81% 从未体检”。",
         "体检类风险因子固定用 checkup_over_1y，避免 8 被误读。"),
        ("V6 · 列裁剪与类型统一", "五年并集 593 列，绝大多数与分析无关；直接建模会带进大量稀疏列与类型冲突",
         "只保留分析口径需要的 37 列：8 个慢病标签 + 可干预因素 + 人口学 + 派生指标；逐列显式 cast 到目标类型，"
         "并保证五年输出列名与顺序完全一致。",
         "输出列整理（pipeline/02_clean_spark.py:319–360）；高缺列不再进入下游。",
         "验收：入库 fact_brfss 37 列，类型与 schema.sql 一致，无类型冲突。",
         "37 列口径固定；分析脚本不再直接读原始 parquet。"),
        ("V7 · Windows 落盘失败（环境逼出来的改写）", "Spark 4.2 缺 winutils.exe，df.write.parquet 直接抛 HADOOP_HOME 异常",
         "清洗算子在 Spark 内完成，但落盘不要用 DataFrameWriter：改成 toLocalIterator 分批取回，用 pyarrow 按批写单文件 parquet。",
         "write_parquet_via_arrow()（pipeline/02_clean_spark.py:81–125），batch_rows=50,000。",
         "验收：输出 38,268,188 字节，回读校验行数 2,136,402 与清洗结果一致。",
         "这条“算子留 Spark、落盘走 Arrow”的写法成了本项目所有 Spark 输出脚本的固定做法。"),
    ]
    for i, (title, trigger, prompt, output, check, result) in enumerate(iters, 1):
        doc.h2(title)
        doc.kv([("触发证据", trigger)])
        doc.p("当时发出的指令（提示词）：", size=9.5, bold=True)
        doc.quote(prompt)
        doc.kv([("模型产出", output), ("验收发现", check), ("收敛结论", result)])
    doc.p("迭代谱系小结：V1 因为“通用清洗会毁样本”被整条否决；V2 确立白名单；V3/V4/V5 三次都是被真实数据打回——"
          "主键撞键、编码方向、特殊码 8，每一次都有可核查的报错或数字；V6/V7 是工程约束（列太多、Windows 落盘）。"
          "七版之后规则才稳定下来，最终清洗脚本 529 行。", size=10)

    doc.h1("三、逐条清洗操作台账（什么操作 · 涉及多少 · 在哪）")
    doc.p("这是“全人工清洗”式问法的等价交代：每条规则的操作、作用对象、涉及数量、代码位置、执行证据。", size=10)
    rows = [
        ["规则 1", "缺失码 → NULL（逐变量白名单）", "29 个原始变量", f"置空后 8 个标签列缺失 3,743–19,251 行不等；genhlth 缺失 5,468 行（0.26%）；medcost 6,602 行（0.31%）", "02_clean_spark.py:207–258"],
        ["规则 2", "BMI = _BMI5/100；越界置空", "2,137,374 行全体", "越界 1,053 行置空；原始缺失 213,753 行；最终 bmi 缺失 214,048（10.02%）", "02_clean_spark.py:254–261"],
        ["规则 3", "收入档调和：_INCOMG1 7 档 → _INCOMG 5 档，库内 8 档", "收入列全部非空行", "income_grp 缺失 436,105 行（20.41%）", "02_clean_spark.py:262–271"],
        ["规则 3.5", "二值字段统一 0/1（1=状态成立）", "10 个二值字段", "smoker3 缺失 122,976；phys_activity 25,651；heavy_drink 1,342,584（62.84%，该变量 2019–2021 未采集）", "02_clean_spark.py:272–276"],
        ["规则 4", "种族调和：_RACE 优先，2022 用 _MRACE2+_HISPANC", "race/hispanic 两列", "race 缺失 49,645（2.32%）；hispanic 26,363（1.23%）", "02_clean_spark.py:277–295"],
        ["规则 5", "8 个慢病标志位：1=是 归一为 0/1", "8 列 × 全部行", "糖尿病 288,055 / 心梗 117,717 / 冠心病 118,932 / 卒中 89,224 / 慢阻肺 169,792 / 哮喘 305,625 / 肾病 89,262 / 抑郁 419,958", "02_clean_spark.py:296–305"],
        ["规则 6", "派生指标：obese、chronic_count、multimorbidity、poor_health", "全体行", "共病（慢病数≥2）386,760 行，18.10%", "02_clean_spark.py:306–318"],
        ["规则 7", "输出列整理 + 主键 seq_key + 类型统一", "输出 37 列", "输出 2,136,402 行；seq_key 唯一值 2,136,402", "02_clean_spark.py:319–360"],
        ["行级过滤", "8 个慢病标志位全为 NULL → 丢行", "2,137,374 行", "丢弃 972 行（0.045%）", "02_clean_spark.py:446–465"],
    ]
    doc.table(["编号", "操作", "作用对象", "涉及数量（实测）", "代码位置"], rows, widths=[1.5, 5.0, 3.2, 5.6, 3.2], size=8.2)

    doc.h1("四、清洗前后对比")
    doc.h2("4.1 行数")
    doc.table(["阶段", "行数", "说明"], [
        ["采集（原始）", f"{CLEAN['rows_in']:,}", "五年并集"],
        ["清洗后", f"{CLEAN['rows_out']:,}", f"丢弃 {CLEAN['rows_dropped_total']:,} 行（标签全空的记录）"],
        ["入库（fact_brfss）", f"{DB['verification']['n_fact']:,}", f"回读核对 count_match={DB['verification']['count_match']}，duplicate_seq_key={DB['verification']['duplicate_seq_key']}"],
    ], widths=[3.6, 3.4, 10.4])
    doc.h2("4.2 关键字段缺失率（清洗后）")
    keys = [k for k in CLEAN["null_rate_after"] if not k.startswith("has_")]
    rows = []
    for k in keys:
        rows.append([k, f"{CLEAN['null_count_after'][k]:,}", "%.2f%%" % (CLEAN["null_rate_after"][k] * 100)])
    half = (len(rows) + 1) // 2
    merged = []
    for i in range(half):
        left = rows[i]
        right = rows[i + half] if i + half < len(rows) else ["", "", ""]
        merged.append(left + right)
    doc.table(["字段", "缺失行数", "缺失率", "字段", "缺失行数", "缺失率"], merged, widths=[3.4, 2.6, 2.0, 3.4, 2.6, 2.0], size=8.2,
              note="分母为 2,136,402 行；heavy_drink 缺失率高是该变量 2019–2021 年未采集所致，不是清洗错误。")
    doc.h2("4.3 八种慢病与共病（清洗后全样本）")
    rows = []
    for k, v in CLEAN["chronic_prevalence"].items():
        rows.append([v.get("name_cn", k), f"{v['n_positive']:,}", f"{v['n_valid']:,}", "%.2f%%" % (v["prevalence"] * 100)])
    doc.table(["慢病", "阳性数", "有效样本", "患病率"], rows, widths=[3.6, 3.4, 3.4, 3.0])

    doc.h1("五、编码口径约定（三条，全项目通用）")
    doc.bullet("二值字段一律 0/1，且 1 = 字段名所描述的状态成立（如 has_diabetes=1 表示有糖尿病；phys_activity=1 表示有闲暇体力活动）。")
    doc.bullet("特殊码按语义转换：MENTHLTH/PHYSHLTH 的 88 = 0 天；CHECKUP1 的 8 = 从未体检，风险因子用 checkup_over_1y = checkup > 1。")
    doc.bullet("缺失保持 NULL，不做均值/众数填充：下游用 LightGBM 的缺失值原生处理，避免用伪造值污染风险分层。")

    doc.h1("六、复现与验证")
    doc.code("""# 清洗（PySpark 本地模式）
python pipeline/02_clean_spark.py
# 建库 + 维表 + 聚合表 + 回读核对
python pipeline/06_build_db.py
# 全流程一键复现（下载→清洗→EDA→特征→训练→建库）
python pipeline/run_all.py""")
    doc.table(["验证项", "期望", "实测"], [
        ["清洗耗时", "—", f"{CLEAN['elapsed_sec']} 秒（engine：{CLEAN['engine']}）"],
        ["输出文件", "data/processed/brfss_clean.parquet", f"{CLEAN['output_bytes']:,} 字节（{CLEAN['output_writer']}）"],
        ["主键唯一性", "seq_key 唯一值数 = 行数", f"{CLEAN['seq_key_distinct']:,} = {CLEAN['rows_out']:,}"],
        ["入库行数核对", "parquet 行数 = 事实表行数", f"{DB['verification']['n_parquet']:,} = {DB['verification']['n_fact']:,}，count_match={DB['verification']['count_match']}"],
        ["主键空值", "0", str(DB["verification"]["null_pk_rows"])],
    ], widths=[3.6, 6.0, 7.8])

    doc.h1("七、附录")
    doc.h2("附录 A · 可复用的清洗提示词骨架")
    doc.code("""你是数据工程助手，面对的是 BRFSS 调查数据（百万级行）。
【已知】缺失码不是 NULL：7/9、77/99 表示不知道/拒答；但同一数字在不同变量含义不同，
        88（None）与 8（Never）是真实取值。
【要求】1) 逐变量给出缺失码白名单，不要用全局规则；
        2) 二值字段统一 0/1，且 1 = 字段名所述状态成立；
        3) 输出主键必须证明唯一性（给出 distinct 与总行数）；
        4) 每条规则都要给出：作用对象、涉及行数、代码行号；
        5) 不要删除含缺失的行，缺失保持 NULL。
【交付】可运行代码 + 一份清洗台账表（操作/数量/位置）。""")
    doc.h2("附录 B · 代码位置")
    doc.table(["文件", "行数", "承担"], [
        ["pipeline/02_clean_spark.py", "529", "全部清洗规则、主键、派生指标、Arrow 落盘、审计日志"],
        ["pipeline/06_build_db.py", "690", "建库、维表、聚合表、回读核对"],
        ["scripts/rebuild_aggregates.py", "—", "聚合表重建与占位行补齐（明细不被触碰）"],
    ], widths=[5.4, 2.0, 9.0])
    doc.h2("附录 C · 三条致命缺陷的现场证据")
    doc.table(["缺陷", "现场证据", "修复与验证"], [
        ["主键撞键", "2019 年 418,268 行，仅 17,419 个不同 SEQNO；_PSU 与 SEQNO 逐行相等不可用；(_STSTR,SEQNO) 组合去重后与总行数完全相等", "seq_key = year_ststr_seqno；distinct = 2,136,402 = 总行数"],
        ["编码方向反转", "_RFBING6：1=否、2=是；_TOTINDA：1=有运动、2=无运动（与慢病标志位方向相反）", "统一 0/1；重度饮酒率 13.27%（错误方向会得到 86.73%）"],
        ["CHECKUP1 的 8", "8 = 从未体检；若按“=1 为已体检”取反，会读出“81% 从未体检”", "checkup_over_1y = checkup > 1；2023 年 0.185928"],
    ], widths=[3.2, 8.4, 5.8], size=8.5)
    return doc.save(OUT / "数据清洗说明_提示词迭代与清洗台账.docx")


def copy_attachments():
    ATT.mkdir(parents=True, exist_ok=True)
    items = [ROOT / "pipeline/01_download.py", ROOT / "pipeline/02_clean_spark.py",
             ROOT / "pipeline/06_build_db.py", ROOT / "pipeline/08_scheduled_ingest.py",
             ROOT / "pipeline/09_selenium_scrape.py", ROOT / "pipeline/run_all.py"]
    for it in items:
        dst = ATT / it.name
        shutil.copy2(it, dst)
    cdir = ATT / "crawler_uci_spider"
    cdir.mkdir(exist_ok=True)
    for f in ("items.py", "pipelines.py", "settings.py", "scrapy.cfg"):
        src = (ROOT / "crawler" / f) if f == "scrapy.cfg" else (ROOT / "crawler/uci_spider" / f)
        if src.exists():
            shutil.copy2(src, cdir / f)
    for sp in (ROOT / "crawler/uci_spider/spiders").glob("*.py"):
        shutil.copy2(sp, cdir / ("spider_" + sp.name))
    n = sum(1 for _ in ATT.rglob("*") if _.is_file())
    return n


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    a = build_collect()
    b = build_clean()
    n = copy_attachments()
    for p in (a, b):
        print("%-58s %8.1f KB" % (p.name, p.stat().st_size / 1024))
    print("代码附件 %d 个文件 -> %s" % (n, ATT))
    (OUT / "README.md").write_text(
        "# 数据采集与清洗交付\n\n"
        "- 数据采集说明_采集代码与维度定义.docx\n"
        "- 数据清洗说明_提示词迭代与清洗台账.docx\n"
        "- 代码附件/：采集与清洗源码原样副本（下载/清洗/建库/定时增量/Selenium/Scrapy/一键复现）\n\n"
        "数据集本身不随本目录交付（约 1.4 GB），来源、数量、频率、维度与校验方式见采集说明；"
        "原始数据交付包见 期末作业/原始数据交付/。\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
