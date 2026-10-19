# -*- coding: utf-8 -*-
"""build_ppt.py — 生成《项目演示PPT.pptx》（16:9，17 页，覆盖要求中的 9 项必备内容）"""
import json
import os
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Cm, Inches, Pt
from pptx.oxml.ns import qn
from lxml import etree

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(SCRIPT_DIR)
ROOT = os.path.dirname(PROJ)
FIG = os.path.join(PROJ, "artifacts", "figures")
SHOT = os.path.join(PROJ, "web", "assets", "screenshots")
MET = os.path.join(PROJ, "artifacts", "metrics")
OUT = os.path.join(ROOT, "项目演示PPT.pptx")

NAVY = RGBColor(0x1F, 0x3B, 0x57)
ACCENT = RGBColor(0x2E, 0x6D, 0xA4)
GREY = RGBColor(0x59, 0x59, 0x59)
LIGHT = RGBColor(0xEE, 0xF3, 0xF8)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
ORANGE = RGBColor(0xC0, 0x5A, 0x1E)

eda = json.load(open(os.path.join(MET, "eda_metrics.json"), encoding="utf-8"))
hyp = json.load(open(os.path.join(MET, "hypothesis_metrics.json"), encoding="utf-8"))
mm = json.load(open(os.path.join(PROJ, "artifacts", "model", "metrics.json"), encoding="utf-8"))
meta = json.load(open(os.path.join(PROJ, "artifacts", "model", "model_meta.json"), encoding="utf-8"))
RES = {r["model"]: r for r in mm["results"]}
N = eda["n_total"]
PV = eda["overall_prevalence"]

prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)
BLANK = prs.slide_layouts[6]
SW, SH = prs.slide_width, prs.slide_height


def cn(run, font="微软雅黑"):
    run.font.name = font
    rPr = run._r.get_or_add_rPr()
    for tag in ("a:ea", "a:cs"):
        el = rPr.find(qn(tag))
        if el is None:
            el = etree.SubElement(rPr, qn(tag))
        el.set("typeface", font)


def text(slide, x, y, w, h, s, size=18, bold=False, color=GREY, align=PP_ALIGN.LEFT,
         font="微软雅黑", spacing=1.15, anchor=MSO_ANCHOR.TOP):
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    lines = s.split("\n")
    for i, ln in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = spacing
        r = p.add_run()
        r.text = ln
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.color.rgb = color
        cn(r, font)
    return tb


def bar(slide, color=NAVY, h=Cm(0.35)):
    sh = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, SW, h)
    sh.fill.solid(); sh.fill.fore_color.rgb = color
    sh.line.fill.background()


def header(slide, title, sub=None):
    bar(slide)
    text(slide, Cm(1.5), Cm(0.9), Cm(24), Cm(1.6), title, size=30, bold=True, color=NAVY, font="黑体")
    ln = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Cm(1.5), Cm(2.55), Cm(3.2), Cm(0.12))
    ln.fill.solid(); ln.fill.fore_color.rgb = ACCENT; ln.line.fill.background()
    if sub:
        text(slide, Cm(1.5), Cm(2.85), Cm(28), Cm(0.9), sub, size=14, color=ACCENT)


def bullets(slide, x, y, w, items, size=16, gap=Cm(0.25)):
    tb = slide.shapes.add_textbox(x, y, w, Cm(10))
    tf = tb.text_frame; tf.word_wrap = True
    for i, it in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.line_spacing = 1.3
        p.space_after = Pt(9)
        r = p.add_run(); r.text = "▸ " + it
        r.font.size = Pt(size); r.font.color.rgb = GREY; cn(r)
    return tb


def pill(slide, x, y, w, h, s, size=12, fill=LIGHT, color=NAVY):
    sh = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h)
    sh.fill.solid(); sh.fill.fore_color.rgb = fill
    sh.line.color.rgb = ACCENT
    tf = sh.text_frame; tf.word_wrap = True
    p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
    r = p.add_run(); r.text = s; r.font.size = Pt(size); r.font.bold = True
    r.font.color.rgb = color; cn(r)
    return sh


def pic(slide, path, x, y, w=None, h=None):
    if os.path.exists(path):
        if w and not h:
            slide.shapes.add_picture(path, x, y, width=w)
        elif h and not w:
            slide.shapes.add_picture(path, x, y, height=h)
        else:
            slide.shapes.add_picture(path, x, y, width=w, height=h)


def newslide():
    return prs.slides.add_slide(BLANK)


# ---- 1 封面 ----
s = newslide()
bg = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, SW, SH)
bg.fill.solid(); bg.fill.fore_color.rgb = NAVY; bg.line.fill.background()
text(s, Cm(2), Cm(5.2), Cm(30), Cm(2.2), "基于 BRFSS 大数据的慢性病患者\n健康风险预测与干预分析",
     size=40, bold=True, color=WHITE, font="黑体", spacing=1.25)
ln = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Cm(2), Cm(11.2), Cm(4), Cm(0.14))
ln.fill.solid(); ln.fill.fore_color.rgb = RGBColor(0x7F, 0xB3, 0xDE); ln.line.fill.background()
text(s, Cm(2), Cm(11.8), Cm(26), Cm(1.2), "大数据分析课程设计 · 综合项目答辩", size=17, color=RGBColor(0xCF, 0xDE, 0xEC))
text(s, Cm(2), Cm(13.0), Cm(26), Cm(1.0), "许宇翔　20240517108　（单人组）", size=15, color=RGBColor(0x9F, 0xBE, 0xD8))
text(s, Cm(2), Cm(14.0), Cm(26), Cm(1.0),
     "数据：CDC BRFSS 2019—2023 　|　 %s 条真实微观数据" % "{:,}".format(N), size=13,
     color=RGBColor(0x8F, 0xAA, 0xC4))

# ---- 2 背景与问题定义 ----
s = newslide(); header(s, "① 项目背景与问题定义", "为什么是“共病”，以及我们要解决什么工程问题")
bullets(s, Cm(1.5), Cm(3.9), Cm(13.2), [
    "慢性病是全球疾病负担主体；多种慢性病共存（共病）放大致残率、再入院率与医疗支出",
    "传统随访滞后，需要把干预窗口前移到“确诊之前”的生活方式与就医可及性层面",
    "BRFSS 兼具样本量、维度完整性与年度连续性，适合做人群风险预测",
], size=15)
box = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Cm(15.2), Cm(3.7), Cm(15.5), Cm(8.2))
box.fill.solid(); box.fill.fore_color.rgb = LIGHT; box.line.color.rgb = ACCENT
text(s, Cm(16.0), Cm(4.1), Cm(13.9), Cm(1.0), "工程问题定义", size=17, bold=True, color=NAVY, font="黑体")
text(s, Cm(16.0), Cm(5.2), Cm(13.9), Cm(6.4),
     "在约 213 万条、跨 5 个年度、口径漂移且存在大量缺失与编码陷阱的真实调查数据上，"
     "构建可复现流水线，量化慢性病共病的可干预危险因素，并训练一个在时间外推下仍稳定、"
     "且不依赖疾病后果变量的预测模型，最终以 RESTful 接口与可视化大屏交付。",
     size=13.5, color=GREY, spacing=1.45)
text(s, Cm(1.5), Cm(12.6), Cm(13), Cm(1.0), "利益相关方", size=14, bold=True, color=ACCENT)
text(s, Cm(1.5), Cm(13.4), Cm(13), Cm(3.4),
     "公共卫生管理者 · 基层医疗机构\n慢病患者本人 · 课程评阅者", size=13, color=GREY, spacing=1.4)

# ---- 3 数据来源与规模 ----
s = newslide(); header(s, "② 数据来源与规模", "“海量”体现在哪里")
pic(s, os.path.join(FIG, "disease_prevalence.png"), Cm(20.5), Cm(4.0), h=Cm(9.4))
bullets(s, Cm(1.5), Cm(3.9), Cm(18.0), [
    "来源：CDC BRFSS 年度微观数据 LLCP，2019—2023 五个年度",
    "原始 %s 条 → 清洗后入库 %s 条（单表 fact_brfss）" % ("{:,}".format(2137374), "{:,}".format(N)),
    "维度：8 类慢性病标志 + BMI/吸烟/活动/饮酒 + 就医可及性 + 社会经济 = 37 列",
    "“海量”的四个体现：①条数超 200 万；②跨 5 年可做时序；③37 维含强异质类别；④单表 378MB，聚合查询 0.2—2.3 秒",
], size=14)
pill(s, Cm(1.5), Cm(11.6), Cm(6.6), Cm(1.3), "原始 2,137,374 条", size=12)
pill(s, Cm(8.6), Cm(11.6), Cm(6.6), Cm(1.3), "清洗后 2,136,402 条", size=12)
pill(s, Cm(15.7), Cm(11.6), Cm(4.4), Cm(1.3), "37 维特征", size=12)

# ---- 4 系统架构 ----
s = newslide(); header(s, "③ 系统架构", "六环节端到端打通")
stages = [("采集", "requests 批量\n断点续传+SHA256"), ("存储", "SQLite\n建表/批量导入/SQL聚合"),
          ("挖掘", "PySpark 清洗+EDA\nsklearn/LightGBM"), ("后端", "FastAPI\n9 个 RESTful 接口"),
          ("前端", "原生 HTML/JS\nECharts 本地内置"), ("可视化", "大屏+联动+下钻\n9 张实拍截图")]
x0, w, gap = Cm(1.6), Cm(4.7), Cm(0.45)
for i, (name, desc) in enumerate(stages):
    x = x0 + i * (w + gap)
    sh = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, Cm(4.6), w, Cm(7.2))
    sh.fill.solid(); sh.fill.fore_color.rgb = LIGHT; sh.line.color.rgb = ACCENT
    text(s, x + Cm(0.3), Cm(4.9), w - Cm(0.6), Cm(1.1), "%d  %s" % (i + 1, name),
         size=16, bold=True, color=NAVY, font="黑体", align=PP_ALIGN.CENTER)
    text(s, x + Cm(0.25), Cm(6.2), w - Cm(0.5), Cm(5.2), desc, size=11, color=GREY,
         align=PP_ALIGN.CENTER, spacing=1.5)
text(s, Cm(1.6), Cm(12.6), Cm(30), Cm(1.2),
     "数据契约：每个环节以 JSON/SQL 表结构交接；原始数据留存 data/raw 并可 SHA256 校验；"
     "整链由 run_all.py 一键复现", size=13, color=ACCENT)

# ---- 5 技术选型 ----
s = newslide(); header(s, "④ 技术选型与理由", "每个选择都有取舍，不是堆名词")
rows = [
    ("采集", "requests", "公开数据无鉴权，requests 足够且可控断点续传"),
    ("存储", "SQLite", "213 万行聚合 1 秒内；零配置、随项目分发、可复现"),
    ("清洗/EDA", "PySpark 4.2 (local[8])", "模板要求 DataFrame API；单机跑通但逻辑与集群一致"),
    ("建模", "scikit-learn + LightGBM", "表格数据上优于深度网络；可直接给特征重要性与 OR"),
    ("对比路径", "Spark MLlib", "交叉验证同一结论，满足模板“路径B”要求"),
    ("后端", "FastAPI + uvicorn", "自带 OpenAPI 文档；异步；类型校验天然契合数据契约"),
    ("前端", "原生 HTML/JS + ECharts", "要求最低形态即可；ECharts 本地内置，断网可演示"),
]
y = Cm(3.9)
for i, (k, v, why) in enumerate(rows):
    bgc = LIGHT if i % 2 == 0 else WHITE
    sh = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Cm(1.5), y, Cm(30.5), Cm(1.28))
    sh.fill.solid(); sh.fill.fore_color.rgb = bgc; sh.line.fill.background()
    text(s, Cm(1.8), y + Cm(0.22), Cm(4.2), Cm(0.9), k, size=12.5, bold=True, color=NAVY)
    text(s, Cm(6.2), y + Cm(0.22), Cm(8.2), Cm(0.9), v, size=12.5, color=ACCENT, bold=True)
    text(s, Cm(14.8), y + Cm(0.22), Cm(16.5), Cm(0.9), why, size=12, color=GREY)
    y += Cm(1.34)

# ---- 6 数据治理与关键修复 ----
s = newslide(); header(s, "⑤ 数据治理与三个关键修复", "结论错不错，往往不在模型而在数据层")
fixes = [
    ("主键撞键", "SEQNO 是层内序号，2019 年 41.8 万行仅 1.7 万个不同值；\n单列做主键会直接违反唯一约束",
     "改为 (year, _STSTR, SEQNO) 组合 → 2,136,402 行零重复"),
    ("编码方向相反", "_RFBING6 是 1=否/2=是，_TOTINDA 是 1=有运动/2=无，\n与慢病标志位“1=是”约定相反",
     "全部二值字段归一化为 0/1 且 1=状态成立 → 酗酒率 86.73% 修正为 13.27%"),
    ("标签泄漏", "genhlth / menthlth / diffwalk 本质是疾病的后果，\n直接入模会让 AUC 虚高却无法用于干预",
     "构造 Set-A 无泄漏特征集作为正式模型，Set-B 仅作性能上限参照"),
]
y = Cm(4.2)
for i, (t, prob, sol) in enumerate(fixes):
    sh = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Cm(1.5), y, Cm(30.5), Cm(3.3))
    sh.fill.solid(); sh.fill.fore_color.rgb = LIGHT; sh.line.color.rgb = ACCENT
    text(s, Cm(2.0), y + Cm(0.35), Cm(8.0), Cm(0.9), "%d. %s" % (i + 1, t), size=15, bold=True, color=ORANGE, font="黑体")
    text(s, Cm(2.0), y + Cm(1.3), Cm(13.0), Cm(1.8), prob, size=10.5, color=GREY, spacing=1.35)
    text(s, Cm(16.0), y + Cm(1.3), Cm(15.5), Cm(1.8), "→ " + sol, size=10.5, color=NAVY, spacing=1.35)
    y += Cm(3.55)

# ---- 7 EDA 发现 ----
s = newslide(); header(s, "⑥ 探索性发现", "分布 · 梯度 · 剂量反应")
pic(s, os.path.join(FIG, "dose_response.png"), Cm(1.5), Cm(3.9), h=Cm(8.0))
pic(s, os.path.join(FIG, "comorbidity_by_income.png"), Cm(17.6), Cm(3.9), h=Cm(8.0))
text(s, Cm(1.5), Cm(12.4), Cm(14), Cm(1.0), "三项可干预因素计数 → 共病率", size=12, bold=True, color=NAVY, align=PP_ALIGN.CENTER)
text(s, Cm(17.6), Cm(12.4), Cm(14), Cm(1.0), "共病率的收入梯度", size=12, bold=True, color=NAVY, align=PP_ALIGN.CENTER)
text(s, Cm(1.5), Cm(13.6), Cm(30), Cm(1.4),
     "剂量—反应严格单调：0 项 11.20% → 1 项 20.10% → 2 项 33.22% → 3 项 43.72%　|　"
     "收入 <1.5 万 35.99% vs ≥5 万 12.32%，相差近 24 个百分点", size=12.5, color=ACCENT)

# ---- 8 假设验证 ----
s = newslide(); header(s, "⑦ 假设验证：调整后 OR", "方式A 分组对比+排干扰　+　方式B 卡方与效应量")
pic(s, os.path.join(FIG, "or_forest.png"), Cm(1.5), Cm(3.7), h=Cm(9.8))
text(s, Cm(18.2), Cm(3.9), Cm(14), Cm(9.6),
     "H1 成立：现吸烟 2.21、肥胖 1.86、\n缺乏体力活动 1.68，调整混杂后仍显著\n\n"
     "H2 成立：收入 ≥5 万 OR=0.337、\n大学 4 年以上 OR=0.723，梯度单调\n\n"
     "H3 部分成立：费用障碍 OR=2.13；\n但“无固定医生 0.53 / 未体检 0.55”\n为**检出偏倚**——有医疗接触者才被诊断，\n不能当作保护因素", size=12.5, color=GREY, spacing=1.5)
text(s, Cm(1.5), Cm(13.9), Cm(30), Cm(1.2),
     "n=2,136,402 时 p 值必然显著，因此一律以效应量与置信区间判读，不靠 p 值说话", size=11.5, color=ORANGE)

# ---- 9 建模 ----
s = newslide(); header(s, "⑧ 预测建模与对比实验", "时间外推切分：训练 2019—2022 / 测试 2023")
pic(s, os.path.join(FIG, "model", "roc_comparison.png"), Cm(1.5), Cm(3.8), h=Cm(8.6))
bullets(s, Cm(19.0), Cm(3.9), Cm(13.0), [
    "六组组合：2 特征集 × 3 模型",
    "LightGBM@Set-A：AUC %.4f，PR-AUC %.4f，F1 %.4f" % (RES["LightGBM_SetA"]["auc_roc"], RES["LightGBM_SetA"]["auc_pr"], RES["LightGBM_SetA"]["f1"]),
    "五折交叉验证 AUC %.4f ± %.4f" % (meta["cv_auc_mean"], meta["cv_auc_std"]),
    "LightGBM@Set-B：AUC %.4f（上限参照）" % RES["LightGBM_SetB"]["auc_roc"],
    "性能差 %.3f，但 Set-B 在真实干预场景拿不到输入 → 采用 Set-A" % (RES["LightGBM_SetB"]["auc_roc"] - RES["LightGBM_SetA"]["auc_roc"]),
], size=12.5)
text(s, Cm(1.5), Cm(12.9), Cm(17.5), Cm(1.2), "ROC 曲线（测试集 2023）", size=12, bold=True, color=NAVY, align=PP_ALIGN.CENTER)

# ---- 10 系统演示 ----
s = newslide(); header(s, "⑨ 核心功能演示", "现场可跑：uvicorn 起服务 → 浏览器打开大屏 → 提交预测")
pic(s, os.path.join(SHOT, "01-dashboard-full.png"), Cm(1.5), Cm(3.7), w=Cm(20.0))
pic(s, os.path.join(SHOT, "04-predict-result.png"), Cm(22.2), Cm(3.7), w=Cm(11.5))
text(s, Cm(1.5), Cm(12.4), Cm(20), Cm(1.0), "可视化大屏（数据全部来自实时 API）", size=11.5, bold=True, color=NAVY, align=PP_ALIGN.CENTER)
text(s, Cm(22.2), Cm(12.4), Cm(11.5), Cm(1.0), "在线个体风险预测（真模型）", size=11.5, bold=True, color=NAVY, align=PP_ALIGN.CENTER)
text(s, Cm(1.5), Cm(13.4), Cm(30), Cm(1.2),
     "实测：9/9 接口 code=0；/predict 输入 68 岁肥胖吸烟者+费用障碍 → 概率 0.6813、高风险；"
     "ECharts 与地图均为本地内置，断网可演示", size=12, color=ACCENT)

# ---- 11 业务洞察 ----
s = newslide(); header(s, "⑩ 业务洞察与干预建议", "从模型结论到可执行动作")
insights = [
    ("筛查规则", "年龄 + 收入 + 吸烟/BMI/活动量组合初筛，而非单一指标", "剂量-反应显示风险是累积放大而非线性相加"),
    ("干预抓手", "戒烟、体重管理、体力活动是三个可量化抓手", "调整后 OR 分别 2.21 / 1.86 / 1.68"),
    ("被低估的一环", "消除费用障碍的效应量级与肥胖相当", "OR 2.13 vs 1.86，常被“只做健康教育”忽略"),
    ("风险沟通", "模型概率经校准，可直接映射高/中/低风险分层随访", "校准曲线贴近对角线"),
    ("伦理红线", "不得据此减少就医；负向 OR 是检出偏倚", "反而应加强无固定医生人群的机会性筛查"),
]
y = Cm(4.0)
for i, (a, b, c) in enumerate(insights):
    sh = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Cm(1.5), y, Cm(30.5), Cm(1.9))
    sh.fill.solid(); sh.fill.fore_color.rgb = LIGHT if i % 2 == 0 else WHITE
    sh.line.color.rgb = ACCENT
    text(s, Cm(2.0), y + Cm(0.5), Cm(6.5), Cm(0.9), a, size=13.5, bold=True, color=NAVY, font="黑体")
    text(s, Cm(9.0), y + Cm(0.5), Cm(13.0), Cm(0.9), b, size=12, color=GREY)
    text(s, Cm(22.5), y + Cm(0.5), Cm(9.0), Cm(0.9), c, size=11, color=ACCENT)
    y += Cm(2.05)

# ---- 12 难点 ----
s = newslide(); header(s, "⑪ 难点与解决方案", "六个真实踩过的坑")
diff = [
    ("Spark 写 parquet 失败", "本机缺 winutils.exe，DataFrameWriter 抛 HADOOP_HOME 异常", "Spark 只算不写，落盘改 Arrow 分批流式"),
    ("中文路径导致 JVM 起不来", "classpath 含中文被 GBK 破坏", "建 ASCII 目录联接 jdk17 / sparkhome"),
    ("Logistic 设计矩阵秩亏", "statsmodels 仅告警，部分系数不可识别", "20 万行抽样带主元 QR 判秩，剔除常量列后全量拟合"),
    ("控制台 GBK 无法输出 ²", "R² 等字符触发 UnicodeEncodeError", "stdout/stderr reconfigure 到 UTF-8"),
    ("pandas 3.x 与 PySpark 4.2 不兼容", "官方警告部分功能可能异常", "回退 pandas 2.3.3"),
    ("matplotlib 中文乱码", "默认字体无中文字形", "显式指定 Microsoft YaHei 并关闭 unicode_minus"),
]
y = Cm(3.9)
for i, (a, b, c) in enumerate(diff):
    bgc = LIGHT if i % 2 == 0 else WHITE
    sh = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Cm(1.5), y, Cm(30.5), Cm(1.5))
    sh.fill.solid(); sh.fill.fore_color.rgb = bgc; sh.line.fill.background()
    text(s, Cm(1.8), y + Cm(0.32), Cm(8.6), Cm(0.9), a, size=11.5, bold=True, color=ORANGE)
    text(s, Cm(10.6), y + Cm(0.32), Cm(11.6), Cm(0.9), b, size=10.5, color=GREY)
    text(s, Cm(22.4), y + Cm(0.32), Cm(9.4), Cm(0.9), "→ " + c, size=10.5, color=NAVY)
    y += Cm(1.56)

# ---- 13 不足与改进 ----
s = newslide(); header(s, "⑫ 不足与改进方向", "诚实交代边界")
bullets(s, Cm(1.5), Cm(3.9), Cm(15.0), [
    "横断面自报数据，无法做严格因果推断，存在检出偏倚",
    "heavy_drink 缺失 62.84%，跨年可比性弱；收入缺失 20.41%",
    "未做复杂抽样加权建模（描述统计已并列报告加权口径）",
    "AUC %.3f 仍有提升空间，缺少生化指标与用药记录" % RES["LightGBM_SetA"]["auc_roc"],
    "未做公平性审计（不同种族/收入组校准差异未量化）",
], size=13)
bullets(s, Cm(16.8), Cm(3.9), Cm(15.0), [
    "引入纵向链接数据，把横断面转随访，做真正因果推断",
    "补充 SHAP 解释与分组校准曲线，量化公平性",
    "高缺失字段改多重插补，而非直接置空",
    "数据量增至千万级时迁移 ClickHouse / 数据湖",
    "模型服务化 + 漂移检测（PSI）触发滚动重训",
], size=13)
text(s, Cm(1.5), Cm(11.4), Cm(15), Cm(1.0), "现存局限", size=15, bold=True, color=ORANGE, font="黑体")
text(s, Cm(16.8), Cm(11.4), Cm(15), Cm(1.0), "改进方向", size=15, bold=True, color=ACCENT, font="黑体")

# ---- 14 分工 ----
s = newslide(); header(s, "⑬ 分工说明与个人贡献", "单人组：全链路独立完成")
bullets(s, Cm(1.5), Cm(3.9), Cm(29.0), [
    "承担范围：数据获取与原始副本留存 · PySpark 清洗与建库 · EDA 与假设检验 · 建模与对比实验 · FastAPI 后端 · ECharts 前端 · 工程化与文档",
    "关键决策：选真实 BRFSS 而非合成数据；坚持时间外推切分而非随机切分；识别并阻断标签泄漏，宁可牺牲 0.046 AUC；把负向 OR 解释为检出偏倚而非保护因素",
    "工作量证据：18 次规范 Git 提交 · 12 张 EDA 图 + 5 张建模图 · 9 个接口 · 9 张界面截图 · 6 份文档 · 完整报告 31 节",
], size=13)
sh = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Cm(1.5), Cm(9.6), Cm(30.5), Cm(4.4))
sh.fill.solid(); sh.fill.fore_color.rgb = LIGHT; sh.line.color.rgb = ACCENT
text(s, Cm(2.2), Cm(10.0), Cm(29), Cm(1.0), "最重要的一条收获", size=15, bold=True, color=NAVY, font="黑体")
text(s, Cm(2.2), Cm(11.2), Cm(29), Cm(2.6),
     "本项目三次最关键的修复（主键、编码方向、标签泄漏）没有一次来自模型层，全部来自数据层与实验设计层——"
     "“数据口径”比“模型调参”更能决定结论的对错。", size=13.5, color=GREY, spacing=1.5)

# ---- 15 结论 ----
s = newslide(); header(s, "⑭ 结论", "")
concl = [
    ("2,136,402", "条真实 BRFSS 数据完成六环节流水线"),
    ("18.10%", "共病率；抑郁 19.76% 与哮喘 14.35% 最高"),
    ("2.21 / 2.13 / 1.86 / 1.68", "现吸烟 / 费用障碍 / 肥胖 / 缺乏活动 的调整后 OR"),
    ("11.20% → 43.72%", "可干预因素 0 → 3 项时的共病率剂量-反应"),
    ("0.7740 / 0.7815", "LightGBM@Set-A 测试集 AUC / 五折 CV AUC"),
    ("9 / 9", "RESTful 接口全部返回 code=0"),
]
y = Cm(4.2)
for i, (k, v) in enumerate(concl):
    sh = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Cm(1.5), y, Cm(30.5), Cm(1.55))
    sh.fill.solid(); sh.fill.fore_color.rgb = LIGHT if i % 2 == 0 else WHITE
    sh.line.color.rgb = ACCENT
    text(s, Cm(2.2), y + Cm(0.35), Cm(11.0), Cm(0.9), k, size=15, bold=True, color=ACCENT)
    text(s, Cm(13.8), y + Cm(0.4), Cm(18.0), Cm(0.9), v, size=12.5, color=GREY)
    y += Cm(1.7)

# ---- 16 附：模型对比表 ----
s = newslide(); header(s, "附：六组模型对比（测试集 2023）", "时间外推切分，非随机切分")
xs = [1.5, 9.0, 14.0, 19.0, 23.5, 27.5]
hs = ["模型 / 特征集", "AUC", "PR-AUC", "F1", "Brier", "备注"]
y = Cm(3.9)
for i, hh in enumerate(hs):
    tb = s.shapes.add_textbox(Cm(xs[i]), y, Cm(5.5), Cm(0.9))
    p = tb.text_frame.paragraphs[0]
    r = p.add_run(); r.text = hh; r.font.size = Pt(12); r.font.bold = True
    r.font.color.rgb = NAVY; cn(r)
y += Cm(1.0)
for i, (k, v) in enumerate(sorted(RES.items(), key=lambda kv: -kv[1]["auc_roc"])):
    bgc = LIGHT if i % 2 == 0 else WHITE
    sh = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Cm(1.5), y, Cm(31.0), Cm(1.15))
    sh.fill.solid(); sh.fill.fore_color.rgb = bgc; sh.line.fill.background()
    note = "正式模型" if k == "LightGBM_SetA" else ("性能上限参照" if k == "LightGBM_SetB" else "")
    vals = [k, "%.4f" % v["auc_roc"], "%.4f" % v["auc_pr"], "%.4f" % v["f1"], "%.4f" % v["brier"], note]
    for j, vv in enumerate(vals):
        tb = s.shapes.add_textbox(Cm(xs[j]), y + Cm(0.22), Cm(5.5), Cm(0.8))
        p = tb.text_frame.paragraphs[0]
        r = p.add_run(); r.text = str(vv); r.font.size = Pt(11)
        r.font.color.rgb = ORANGE if (j == 5 and note == "正式模型") else GREY
        if j == 5 and note == "正式模型":
            r.font.bold = True
        cn(r)
    y += Cm(1.2)

# ---- 17 致谢 ----
s = newslide()
bg = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, SW, SH)
bg.fill.solid(); bg.fill.fore_color.rgb = NAVY; bg.line.fill.background()
text(s, Cm(2), Cm(6.0), Cm(30), Cm(2.0), "感谢聆听", size=40, bold=True, color=WHITE, font="黑体", align=PP_ALIGN.CENTER)
text(s, Cm(2), Cm(9.2), Cm(30), Cm(1.4), "现场演示：http://127.0.0.1:8000　+　web/index.html",
     size=15, color=RGBColor(0xCF, 0xDE, 0xEC), align=PP_ALIGN.CENTER)
text(s, Cm(2), Cm(11.0), Cm(30), Cm(1.2), "许宇翔　20240517108", size=14,
     color=RGBColor(0x9F, 0xBE, 0xD8), align=PP_ALIGN.CENTER)

prs.save(OUT)
print("已生成：%s（%d 页，%.1f KB）" % (OUT, len(prs.slides.__iter__.__self__._sldIdLst), os.path.getsize(OUT) / 1024))
