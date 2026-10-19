# -*- coding: utf-8 -*-
"""build_ppt.py — 课程二《海量数据挖掘分析与可视化实战》演示 PPT

按《综合项目要求》"项目演示PPT"的 9 项必备内容组织。
"""
import json
import os
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Cm, Inches, Pt
from pptx.oxml.ns import qn
from lxml import etree

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
FIG = os.path.join(PROJ, "artifacts", "figures")
SNS = os.path.join(FIG, "seaborn")
SHOT = os.path.join(PROJ, "web", "assets", "screenshots")
MET = os.path.join(PROJ, "artifacts", "metrics")
OUT = os.path.join(os.path.dirname(PROJ), "海量数据挖掘分析与可视化实战_项目演示.pptx")

NAVY = RGBColor(0x1F, 0x3B, 0x57)
ACCENT = RGBColor(0x2E, 0x6D, 0xA4)
GREY = RGBColor(0x55, 0x5F, 0x6B)
LIGHT = RGBColor(0xEE, 0xF3, 0xF8)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
ORANGE = RGBColor(0xC0, 0x5A, 0x1E)
GREEN = RGBColor(0x2E, 0x7D, 0x32)


def opt(n):
    p = os.path.join(MET, n)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}


eda = opt("eda_metrics.json")
mm = json.load(open(os.path.join(PROJ, "artifacts", "model", "metrics.json"), encoding="utf-8"))
meta = json.load(open(os.path.join(PROJ, "artifacts", "model", "model_meta.json"), encoding="utf-8"))
tuning = opt("tuning_metrics.json")
RES = {r["model"]: r for r in mm["results"]}
N = eda.get("n_total", 2136402)

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
         font="微软雅黑", spacing=1.15):
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.TOP
    for i, ln in enumerate(s.split("\n")):
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
    text(slide, Cm(1.4), Cm(0.85), Cm(30), Cm(1.5), title, size=29, bold=True, color=NAVY, font="黑体")
    ln = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Cm(1.4), Cm(2.45), Cm(3.0), Cm(0.11))
    ln.fill.solid(); ln.fill.fore_color.rgb = ACCENT; ln.line.fill.background()
    if sub:
        text(slide, Cm(1.4), Cm(2.7), Cm(30), Cm(0.9), sub, size=13.5, color=ACCENT)


def bullets(slide, x, y, w, items, size=15):
    tb = slide.shapes.add_textbox(x, y, w, Cm(11))
    tf = tb.text_frame; tf.word_wrap = True
    for i, it in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.line_spacing = 1.3
        p.space_after = Pt(8)
        r = p.add_run(); r.text = "▸ " + it
        r.font.size = Pt(size); r.font.color.rgb = GREY; cn(r)
    return tb


def pic(slide, path, x, y, w=None, h=None):
    if os.path.exists(path):
        if w and not h:
            slide.shapes.add_picture(path, x, y, width=w)
        elif h and not w:
            slide.shapes.add_picture(path, x, y, height=h)
        elif w and h:
            slide.shapes.add_picture(path, x, y, width=w, height=h)


def newslide():
    return prs.slides.add_slide(BLANK)


def card(slide, x, y, w, h, fill=LIGHT, line=ACCENT):
    sh = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h)
    sh.fill.solid(); sh.fill.fore_color.rgb = fill
    sh.line.color.rgb = line
    return sh


# ---------- 1 封面 ----------
s = newslide()
bg = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, SW, SH)
bg.fill.solid(); bg.fill.fore_color.rgb = NAVY; bg.line.fill.background()
text(s, Cm(2), Cm(4.6), Cm(30), Cm(2.6),
     "慢性病患者健康风险预测与干预\n海量数据挖掘分析与可视化实战",
     size=34, bold=True, color=WHITE, font="黑体", spacing=1.3)
ln = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Cm(2), Cm(10.2), Cm(4), Cm(0.13))
ln.fill.solid(); ln.fill.fore_color.rgb = RGBColor(0x7F, 0xB3, 0xDE); ln.line.fill.background()
text(s, Cm(2), Cm(10.8), Cm(28), Cm(1.2), "六环节全链路：采集 → 存储 → 挖掘 → 后端 → 前端 → 可视化",
     size=14.5, color=RGBColor(0xCF, 0xDE, 0xEC))
text(s, Cm(2), Cm(12.0), Cm(28), Cm(1.0), "许宇翔　20240517108　（单人组）", size=14,
     color=RGBColor(0x9F, 0xBE, 0xD8))
text(s, Cm(2), Cm(13.0), Cm(28), Cm(1.0), "数据：CDC BRFSS 2019—2023 　|　 %s 条真实微观数据" % "{:,}".format(N),
     size=12.5, color=RGBColor(0x8F, 0xAA, 0xC4))

# ---------- 2 背景与问题 ----------
s = newslide(); header(s, "① 项目背景与问题定义")
bullets(s, Cm(1.4), Cm(3.4), Cm(14.2), [
    "慢性病共病放大致残率、再入院率与医疗支出，传统随访滞后",
    "需要把干预窗口前移到确诊之前的生活方式与就医可及性",
    "BRFSS 兼具样本量、维度完整性与年度连续性，适合风险预测",
    "本课程落点不是单个模型，而是六环节端到端可运行的系统",
], size=13.5)
card(s, Cm(15.8), Cm(3.3), Cm(16.4), Cm(9.4))
text(s, Cm(16.5), Cm(3.7), Cm(15.0), Cm(1.0), "要交付什么", size=17, bold=True, color=NAVY, font="黑体")
text(s, Cm(16.5), Cm(4.9), Cm(15.2), Cm(7.6),
     "一条覆盖六个环节的完整流水线：\n\n"
     "① 采集：可复现脚本 + SHA256 校验\n"
     "② 存储：关系库建表 / 批量导入 / SQL 聚合\n"
     "③ 挖掘：清洗 + EDA + 建模 + 调优对比\n"
     "④ 后端：RESTful 接口 + 统一数据契约\n"
     "⑤ 前端：可视化大屏\n"
     "⑥ 可视化：联动、下钻、地图\n\n"
     "并且必须能现场演示，不能只播录屏。",
     size=12, color=GREY, spacing=1.5)

# ---------- 3 数据来源与规模 ----------
s = newslide(); header(s, "② 数据来源与数据规模", "“海量”体现在哪里")
pic(s, os.path.join(FIG, "disease_prevalence.png"), Cm(18.8), Cm(3.5), h=Cm(7.2))
bullets(s, Cm(1.4), Cm(3.4), Cm(16.4), [
    "来源：CDC BRFSS 年度微观数据（2019—2023 五个年度）",
    "原始 %s 条 → 清洗后入库 %s 条" % ("{:,}".format(2137374), "{:,}".format(N)),
    "维度：8 类慢病 + 行为危险因素 + 就医可及性 + 社会经济 = 37 列",
    "单表 378MB，聚合查询 17—640ms",
], size=13)
for i, (v, k) in enumerate([("2,137,374", "原始记录数"), ("2,136,402", "入库记录数"),
                            ("5 年", "时间跨度"), ("54 个", "州/属地覆盖")]):
    x = Cm(1.4 + i * 4.15)
    card(s, x, Cm(10.1), Cm(3.85), Cm(2.2), WHITE, ACCENT)
    text(s, x, Cm(10.4), Cm(3.85), Cm(1.0), v, size=15, bold=True, color=ACCENT, align=PP_ALIGN.CENTER)
    text(s, x, Cm(11.4), Cm(3.85), Cm(0.8), k, size=10.5, color=GREY, align=PP_ALIGN.CENTER)
text(s, Cm(1.4), Cm(12.7), Cm(32), Cm(1.2),
     "“海量”的四个体现：①条数超两百万　②跨五年可做时序　③37 维含强异质类别　④库内聚合秒级响应",
     size=12, color=ORANGE)

# ---------- 4 系统架构 ----------
s = newslide(); header(s, "③ 系统架构", "六环节端到端打通，数据契约贯穿全程")
stages = [("1 采集", "requests + Scrapy\n+ Selenium\n断点续传/SHA256"),
          ("2 存储", "SQLite\n建表/批量导入\nSQL 聚合"),
          ("3 挖掘", "PySpark 清洗+EDA\nLightGBM 建模\n网格调优对比"),
          ("4 后端", "FastAPI\n11 个接口\nJWT 鉴权"),
          ("5 前端", "原生 JS + ECharts\nVue 3 组件化版\n联动与下钻"),
          ("6 可视化", "大屏 + 地图\n9 张实拍截图\n断网可演示")]
x0, w, gap = Cm(1.3), Cm(4.85), Cm(0.42)
for i, (name, desc) in enumerate(stages):
    x = x0 + i * (w + gap)
    card(s, x, Cm(4.0), w, Cm(7.2))
    text(s, x + Cm(0.2), Cm(4.3), w - Cm(0.4), Cm(1.1), name, size=15, bold=True,
         color=NAVY, font="黑体", align=PP_ALIGN.CENTER)
    text(s, x + Cm(0.15), Cm(5.6), w - Cm(0.3), Cm(5.2), desc, size=10, color=GREY,
         align=PP_ALIGN.CENTER, spacing=1.5)
text(s, Cm(1.3), Cm(11.9), Cm(32), Cm(1.8),
     "统一数据契约：所有接口返回 {code, message, data, traceId, timestamp}\n"
     "原始数据留存 data/raw 并可 SHA256 校验；整链由 pipeline 脚本一键复现",
     size=11.5, color=ACCENT, spacing=1.4)

# ---------- 5 技术选型 ----------
s = newslide(); header(s, "④ 技术选型与理由", "每个选择都有取舍")
rows = [
    ("采集", "requests / Scrapy / Selenium", "公开数据用 requests；动态渲染用 Selenium；批量规整用 Scrapy"),
    ("存储", "SQLite", "213 万行聚合 17ms；零配置、随项目分发、可复现"),
    ("挖掘", "PySpark + LightGBM", "分布式 API 清洗；GBDT 在表格数据上优于深度网络"),
    ("后端", "FastAPI + JWT", "自带 OpenAPI 文档；Pydantic 校验契合数据契约"),
    ("前端", "原生 JS + ECharts / Vue 3", "原生版零构建可演示；Vue 版展示组件化能力"),
    ("工程化", "Git + pytest + Docker", "43 个用例；容器化配置；密钥由环境变量注入"),
]
y = Cm(3.5)
for i, (k, v, why) in enumerate(rows):
    sh = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Cm(1.3), y, Cm(31.4), Cm(1.5))
    sh.fill.solid(); sh.fill.fore_color.rgb = LIGHT if i % 2 == 0 else WHITE
    sh.line.fill.background()
    text(s, Cm(1.6), y + Cm(0.35), Cm(3.2), Cm(0.9), k, size=12.5, bold=True, color=NAVY)
    text(s, Cm(5.1), y + Cm(0.35), Cm(8.0), Cm(0.9), v, size=11.5, color=ACCENT, bold=True)
    text(s, Cm(13.4), y + Cm(0.35), Cm(19.0), Cm(0.9), why, size=11, color=GREY)
    y += Cm(1.56)

# ---------- 6 核心功能演示 ----------
s = newslide(); header(s, "⑤ 核心功能现场演示", "uvicorn 起服务 → 浏览器打开大屏 → 提交预测")
pic(s, os.path.join(SHOT, "02-dashboard-top.png"), Cm(1.3), Cm(3.9), w=Cm(16.4))
pic(s, os.path.join(SHOT, "04-predict-result.png"), Cm(18.9), Cm(3.9), w=Cm(13.2))
text(s, Cm(1.3), Cm(14.6), Cm(16.4), Cm(0.9), "可视化大屏（数据全部来自实时 API）",
     size=11, bold=True, color=NAVY, align=PP_ALIGN.CENTER)
text(s, Cm(18.9), Cm(8.8), Cm(13.2), Cm(0.9), "在线个体风险预测（真模型 + JWT）",
     size=11, bold=True, color=NAVY, align=PP_ALIGN.CENTER)
text(s, Cm(18.9), Cm(10.1), Cm(13.2), Cm(5.6),
     "实测 9/9 业务接口 code=0\n/risk/factors 17ms\n/risk/stratify 37ms\n\n"
     "未带令牌 → 401\n登录换令牌 → 预测成功\n68 岁肥胖吸烟者 → 高风险\n\n"
     "ECharts 与地图本地内置\n断网亦可演示", size=10.5, color=GREY, spacing=1.35)

# ---------- 7 可视化成果 ----------
s = newslide(); header(s, "⑥ 可视化成果与业务洞察", "图表选型有依据，能讲出一个故事")
pic(s, os.path.join(SNS, "sns_smoker_rate.png") if os.path.exists(os.path.join(SNS, "sns_smoker_rate.png"))
    else os.path.join(FIG, "risk_factor_grouped.png"), Cm(1.3), Cm(3.8), h=Cm(7.4))
pic(s, os.path.join(SNS, "sns_income_gradient.png") if os.path.exists(os.path.join(SNS, "sns_income_gradient.png"))
    else os.path.join(FIG, "comorbidity_by_income.png"), Cm(17.4), Cm(3.8), h=Cm(7.4))
text(s, Cm(1.3), Cm(11.6), Cm(15.5), Cm(0.9), "吸烟状态 × 共病率（Seaborn 95%CI）",
     size=10.5, bold=True, color=NAVY, align=PP_ALIGN.CENTER)
text(s, Cm(17.4), Cm(11.6), Cm(15.0), Cm(0.9), "共病率的收入梯度",
     size=10.5, bold=True, color=NAVY, align=PP_ALIGN.CENTER)
text(s, Cm(1.3), Cm(12.7), Cm(32), Cm(1.6),
     "业务洞察：①筛查规则用「年龄+收入+吸烟/BMI/活动量」组合而非单一指标；"
     "②戒烟、控重、增活动的调整后 OR 分别为 2.21/1.86/1.68；"
     "③消除费用障碍的效应（OR 2.13）与肥胖相当，却常被「只做健康教育」忽略。",
     size=10.5, color=ORANGE, spacing=1.4)

# ---------- 8 模型与调优 ----------
s = newslide(); header(s, "⑥ 附：建模与调优对比", "时间外推切分，测试集为 2023 年")
pic(s, os.path.join(FIG, "model", "roc_comparison.png"), Cm(1.3), Cm(3.7), h=Cm(8.0))
rows = [[k.split("_")[0], k.split("_")[1], "%.4f" % v["auc_roc"], "%.4f" % v["auc_pr"]]
        for k, v in sorted(RES.items(), key=lambda kv: -kv[1]["auc_roc"])]
y = Cm(3.9)
for i, hh in enumerate(["模型", "特征集", "AUC", "PR-AUC"]):
    text(s, Cm(17.6 + i * 3.6), y, Cm(3.4), Cm(0.8), hh, size=11, bold=True, color=NAVY)
y += Cm(1.0)
for i, r in enumerate(rows):
    sh = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Cm(17.4), y, Cm(15.0), Cm(1.0))
    sh.fill.solid(); sh.fill.fore_color.rgb = LIGHT if i % 2 == 0 else WHITE
    sh.line.fill.background()
    for j, v in enumerate(r):
        text(s, Cm(17.6 + j * 3.6), y + Cm(0.2), Cm(3.4), Cm(0.7), str(v), size=10.5, color=GREY)
    y += Cm(1.06)
gain = tuning.get("auc_gain_on_test")
txt = "调优实验：4 组网格 × 2 折 CV。最优参数 num_leaves=63 / lr=0.1，\n"
txt += "CV AUC 由 0.7799 提升至 0.7802，但测试集 AUC 反而 %+.4f。\n" % (gain if gain is not None else 0)
txt += "结论：默认参数已接近该特征集上限，调优收益有限——如实报告，不粉饰。"
text(s, Cm(17.4), y + Cm(0.4), Cm(15.2), Cm(4.4), txt, size=10, color=ORANGE, spacing=1.4)

prs.save(OUT)
print("已有页面:", len(prs.slides._sldIdLst))
print("阶段性保存:", OUT)

# ---------- 9 难点与解决方案 ----------
s = newslide(); header(s, "⑦ 难点与解决方案", "七个真实踩过的坑")
diff = [
    ("Spark 写 parquet 失败", "缺 winutils.exe，抛 HADOOP_HOME 异常", "Spark 只算不写，落盘改 Arrow 分批"),
    ("中文路径 JVM 起不来", "classpath 含中文被 GBK 破坏", "建 ASCII 目录联接 jdk17/sparkhome"),
    ("Scrapy 零产出", "2.19 已移除 start_requests，改用异步 start", "迁移到 async start() 生成器"),
    ("Scrapy 仍零产出", "UCI 的 robots.txt 返回 HTML，被判全禁止", "关闭该中间件并保持 1.2s 礼貌延迟"),
    ("Selenium 无驱动", "Selenium Manager 联网下载失败", "手动下载 msedgedriver 并指定本地路径"),
    ("Spark 模型不吃 NaN", "Vector 含 NaN 直接抛异常", "加 Imputer 中位数填补"),
    ("Logistic 矩阵秩亏", "常量列使系数不可识别", "带主元 QR 判秩后剔除常量列"),
]
y = Cm(3.4)
for i, (a, b, c) in enumerate(diff):
    sh = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Cm(1.3), y, Cm(31.4), Cm(1.42))
    sh.fill.solid(); sh.fill.fore_color.rgb = LIGHT if i % 2 == 0 else WHITE
    sh.line.fill.background()
    text(s, Cm(1.6), y + Cm(0.3), Cm(7.6), Cm(0.85), a, size=10.5, bold=True, color=ORANGE)
    text(s, Cm(9.4), y + Cm(0.3), Cm(11.6), Cm(0.85), b, size=9.5, color=GREY)
    text(s, Cm(21.3), y + Cm(0.3), Cm(11.0), Cm(0.85), "→ " + c, size=9.5, color=NAVY)
    y += Cm(1.48)
text(s, Cm(1.3), Cm(13.9), Cm(31), Cm(0.9),
     "共同规律：真正卡住进度的不是算法，而是环境与数据口径。", size=11, color=ACCENT)

# ---------- 10 加分项 ----------
s = newslide(); header(s, "⑦ 附：加分项实现清单", "除分布式数据库外全部实现（按要求排除）")
bonus = [
    ("采集", "Scrapy 框架", "10 条真实记录"),
    ("采集", "Selenium 动态渲染", "无头 Edge 渲染分页"),
    ("采集", "定时增量采集", "--once / --cron 双模式"),
    ("分析", "Spark", "PySpark local[8]"),
    ("分析", "模型调优与对比", "4 组网格 + 6 组对比"),
    ("分析", "Matplotlib / Seaborn", "4 张 Seaborn 图"),
    ("服务", "Swagger 接口文档", "/docs 自动生成"),
    ("服务", "JWT 鉴权", "登录签发 + 401 拦截"),
    ("展示", "Vue 组件化", "4 图表组件 + 预测组件"),
    ("展示", "大屏适配", "1440 三列 / 768 单列"),
    ("展示", "图表联动与下钻", "4 图 click 联动"),
    ("展示", "地图可视化", "州级热力地图"),
    ("工程", "单元测试", "43 passed"),
    ("工程", "部署脚本", "start_api.ps1"),
    ("工程", "Docker", "Dockerfile + compose"),
    ("工程", "密钥不入库", ".env + gitignore"),
]
cols, cw = 4, Cm(7.7)
for i, (sec, name, ev) in enumerate(bonus):
    ri, ci = divmod(i, cols)
    x = Cm(1.3) + ci * cw
    y = Cm(3.4) + ri * Cm(2.35)
    sh = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, y, cw - Cm(0.35), Cm(2.05))
    sh.fill.solid(); sh.fill.fore_color.rgb = LIGHT
    sh.line.color.rgb = ACCENT
    text(s, x + Cm(0.25), y + Cm(0.22), cw - Cm(0.8), Cm(0.7), sec + " · " + name,
         size=9.5, bold=True, color=NAVY)
    text(s, x + Cm(0.25), y + Cm(1.0), cw - Cm(0.8), Cm(0.8), ev, size=8.5, color=GREY)
text(s, Cm(1.3), Cm(13.6), Cm(31), Cm(0.9),
     "未实现：分布式数据库（Hive / ClickHouse）——本机不便做分布式部署，按要求排除。",
     size=10.5, color=ORANGE)

# ---------- 11 不足与改进 ----------
s = newslide(); header(s, "⑧ 不足与改进方向", "诚实交代边界")
bullets(s, Cm(1.3), Cm(3.5), Cm(15.0), [
    "横断面自报数据，存在检出偏倚，无严格因果",
    "heavy_drink 缺失 62.84%，跨年可比性弱",
    "未做复杂抽样加权建模",
    "AUC %.3f 仍受限于调查型变量" % RES["LightGBM_SetA"]["auc_roc"],
    "Docker 仅完成配置，未实际构建验证",
], size=12.5)
bullets(s, Cm(16.9), Cm(3.5), Cm(15.0), [
    "引入纵向链接数据，把横断面转随访",
    "补充 SHAP 与分组校准，量化公平性",
    "高缺失字段改多重插补",
    "数据量增至千万级时迁移 ClickHouse",
    "模型服务化 + PSI 漂移检测触发重训",
], size=12.5)
text(s, Cm(1.3), Cm(10.6), Cm(15), Cm(0.9), "现存局限", size=14, bold=True, color=ORANGE, font="黑体")
text(s, Cm(16.9), Cm(10.6), Cm(15), Cm(0.9), "改进方向", size=14, bold=True, color=ACCENT, font="黑体")
card(s, Cm(1.3), Cm(11.8), Cm(31.2), Cm(3.0), WHITE, ACCENT)
text(s, Cm(2.0), Cm(12.1), Cm(30), Cm(2.6),
     "中期整改说明：本项目在开发过程中修正了三处会导致结论错误的问题——\n"
     "主键撞键（SEQNO 非唯一）、编码方向反转（酗酒率 86.73% → 13.27%）、标签泄漏（AUC 虚高 0.046）。\n"
     "均已在文档中留痕并可复现验证。",
     size=10.5, color=GREY, spacing=1.5)

# ---------- 12 分工 ----------
s = newslide(); header(s, "⑨ 分工说明与个人贡献", "单人组：全链路独立完成")
bullets(s, Cm(1.3), Cm(3.5), Cm(31.0), [
    "承担范围：采集脚本 · PySpark 清洗与建库 · EDA 与建模 · FastAPI 后端 · ECharts/Vue 前端 · 工程化与文档",
    "交付规模：Git 提交数十次 · 11 个接口 · 43 个测试用例 · 9 张界面截图 · 8 份文档 · 17+ 张分析图",
    "关键决策：选真实数据而非合成数据；时间外推切分而非随机切分；识别并阻断标签泄漏，宁可牺牲 0.046 AUC",
    "工程取舍：查询接口保持公开（评阅人零门槛演示），仅写操作 /predict 要求 JWT",
], size=12.5)
card(s, Cm(1.3), Cm(9.4), Cm(31.2), Cm(4.6))
text(s, Cm(2.0), Cm(9.8), Cm(30), Cm(1.0), "最重要的一条经验", size=14, bold=True, color=NAVY, font="黑体")
text(s, Cm(2.0), Cm(11.0), Cm(30), Cm(2.8),
     "本项目三次最关键的修复（主键、编码方向、标签泄漏）没有一次来自算法层，\n"
     "全部来自数据层与实验设计层——数据口径比模型调参更能决定结论的对错。",
     size=12.5, color=GREY, spacing=1.5)

# ---------- 13 结论 ----------
s = newslide(); header(s, "结论", "")
concl = [
    ("2,136,402", "条真实数据完成六环节流水线"),
    ("6 / 6", "环节全部自研打通，可现场演示"),
    ("11", "个 RESTful 接口，全部返回统一信封"),
    ("43", "个单元测试全部通过"),
    ("0.7740 / 0.7815", "LightGBM@Set-A 测试 AUC / 五折 CV AUC"),
    ("16 / 16", "加分项实现（仅排除分布式数据库）"),
]
y = Cm(4.0)
for i, (k, v) in enumerate(concl):
    sh = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Cm(1.4), y, Cm(31.0), Cm(1.5))
    sh.fill.solid(); sh.fill.fore_color.rgb = LIGHT if i % 2 == 0 else WHITE
    sh.line.color.rgb = ACCENT
    text(s, Cm(2.0), y + Cm(0.33), Cm(11.0), Cm(0.9), k, size=14, bold=True, color=ACCENT)
    text(s, Cm(13.6), y + Cm(0.38), Cm(18.4), Cm(0.9), v, size=11.5, color=GREY)
    y += Cm(1.65)

# ---------- 14 致谢 ----------
s = newslide()
bg = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, SW, SH)
bg.fill.solid(); bg.fill.fore_color.rgb = NAVY; bg.line.fill.background()
text(s, Cm(2), Cm(5.8), Cm(30), Cm(2.0), "感谢聆听", size=40, bold=True, color=WHITE,
     font="黑体", align=PP_ALIGN.CENTER)
text(s, Cm(2), Cm(9.0), Cm(30), Cm(1.4), "现场演示：uvicorn 起服务于 8000 端口 → 打开 web/index.html",
     size=14, color=RGBColor(0xCF, 0xDE, 0xEC), align=PP_ALIGN.CENTER)
text(s, Cm(2), Cm(10.6), Cm(30), Cm(1.2), "Vue 组件化版：web/vue/index.html　|　接口文档：/docs",
     size=12.5, color=RGBColor(0x9F, 0xBE, 0xD8), align=PP_ALIGN.CENTER)
text(s, Cm(2), Cm(12.2), Cm(30), Cm(1.0), "许宇翔　20240517108", size=13,
     color=RGBColor(0x8F, 0xAA, 0xC4), align=PP_ALIGN.CENTER)

prs.save(OUT)
print("总页数:", len(prs.slides._sldIdLst))
print("已生成:", OUT)
print("大小: %.1f KB" % (os.path.getsize(OUT) / 1024))
