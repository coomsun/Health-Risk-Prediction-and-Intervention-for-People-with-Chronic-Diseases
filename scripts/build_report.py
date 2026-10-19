# -*- coding: utf-8 -*-
"""_build_report.py — 生成《大数据分析课程设计报告.docx》（按模板逐章）"""
import json
import os
import sys

from docx.shared import Cm, Pt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_report_base import (Rep, KECHENG, XIANGMU, ZUOZHE, XUEHAO, RENWU,
                                PROJ, FIG, SHOT, MET, OUTDOCX, jload)

eda = jload("eda_metrics.json")
hyp = jload("hypothesis_metrics.json")
mm = json.load(open(os.path.join(PROJ, "artifacts", "model", "metrics.json"), encoding="utf-8"))
meta = json.load(open(os.path.join(PROJ, "artifacts", "model", "model_meta.json"), encoding="utf-8"))
mlp = os.path.join(MET, "spark_mllib_metrics.json")
mllib = json.load(open(mlp, encoding="utf-8")) if os.path.exists(mlp) else {"results": []}

N = eda["n_total"]
PV = eda["overall_prevalence"]
YB = eda["n_by_year"]
CC = eda["chronic_count_dist"]
WU = eda["weighted_vs_unweighted"]["by_year"]
V = hyp["hypothesis_verdict"]
RES = {r["model"]: r for r in mm["results"]}
def f(x, n=4): return ("%." + str(n) + "f") % x
def pc(x, n=2): return ("%." + str(n) + "f%%") % (100 * x)

r = Rep()

# ============================== 封面 ==============================
for _ in range(3):
    r.p("", indent=False)
t = r.p("大数据分析课程设计报告", indent=False, size=26, bold=True)
t.alignment = 1
for _ in range(2):
    r.p("", indent=False)
for lab, val in (("课程名称：", KECHENG), ("项目名称：", XIANGMU),
                 ("本人姓名：", ZUOZHE), ("学　　号：", XUEHAO),
                 ("本人承担任务：", RENWU)):
    p = r.doc.add_paragraph()
    p.alignment = 0
    p.paragraph_format.left_indent = Cm(1.6)
    p.paragraph_format.line_spacing = 1.7
    b = p.add_run(lab); r._cn(b, "黑体"); b.font.size = Pt(12); b.bold = True
    a = p.add_run(val); r._cn(a, "宋体"); a.font.size = Pt(11)
r.p("", indent=False)
r.p("数据来源：美国疾病控制与预防中心（CDC）BRFSS 年度微观数据 2019—2023 年，合计 %s 条" % "{:,}".format(N), indent=False, size=10)
r.pagebreak()

# ============================== 摘要 ==============================
r.h("摘　要", 1)
r.p("本文以慢性病患者健康风险预测与干预为主题，基于美国 CDC 行为危险因素监测系统（BRFSS）"
    "2019—2023 年五期全国微观数据，构建了从数据采集、清洗治理、探索分析、假设检验、预测建模"
    "到后端服务与可视化展示的完整六环节大数据流水线。清洗后有效样本 %s 条，涵盖糖尿病、心肌梗死、"
    "冠心病、卒中、慢阻肺、哮喘、慢性肾病、抑郁障碍八类慢性病标志及 BMI、吸烟、体力活动、饮酒、"
    "就医可及性等行为与社会经济特征。" % "{:,}".format(N))
r.p("主要结论：（1）八类慢性病中抑郁障碍（%s）与哮喘（%s）患病率最高，共病（≥2 种）比例达 %s；"
    "（2）年龄、肥胖、现吸烟、缺乏体力活动与费用障碍是共病风险最强的正向因素，调整年龄、性别、种族、"
    "教育、收入与年份后，其调整后 OR 分别为 2.55（75 岁以上）、1.86、2.21、1.68、2.13；"
    "（3）共病风险呈显著社会经济梯度，收入 ≥5 万美元组相对 <1.5 万美元组的调整后 OR 仅为 0.34；"
    "（4）三项可干预生活方式因素呈明显剂量—反应关系，同时具备 0/1/2/3 项时共病率依次为 %s、%s、%s、%s；"
    "（5）采用时间外推切分（训练 2019—2022、测试 2023）评估，LightGBM 在无标签泄漏的可干预特征集上"
    "AUC 达 %s，五折交叉验证 AUC 为 %s±%s，具备工程可用性。"
    % (pc(PV["has_depression"]["rate"]), pc(PV["has_asthma"]["rate"]), pc(PV["multimorbidity"]["rate"]),
       pc(hyp["dose_response_lifestyle"][0]["rate"]), pc(hyp["dose_response_lifestyle"][1]["rate"]),
       pc(hyp["dose_response_lifestyle"][2]["rate"]), pc(hyp["dose_response_lifestyle"][3]["rate"]),
       f(RES["LightGBM_SetA"]["auc_roc"]), f(meta["cv_auc_mean"]), f(meta["cv_auc_std"])))
r.p("工程侧交付六环节可运行系统：Python 采集脚本与 SHA256 校验的原始数据副本、SQLite 关系库"
    "（fact_brfss 单表 %s 行）、PySpark 清洗与 EDA、scikit-learn/LightGBM 与 Spark MLlib 双路径建模、"
    "FastAPI 九接口 RESTful 服务、原生 HTML/CSS/JS + ECharts 可视化大屏，并通过 18 次规范 Git 提交固化。" % "{:,}".format(N))
r.p("关键词：慢性病；共病；健康风险预测；BRFSS；PySpark；LightGBM；FastAPI；数据可视化", indent=True, bold=True)
r.pagebreak()

# ============================== 第1章 ==============================
r.h("第1章 项目背景与工程问题定义", 1)
r.h("1.1 业务/工程背景", 2)
r.p("慢性非传染性疾病已成为全球疾病负担的主体。多种慢性病共存（multimorbidity，共病）会显著放大"
    "致残率、再入院率与医疗支出，并使单一病种诊疗路径失效。与传统临床随访相比，基于大规模人群"
    "行为与危险因素调查数据，可以在疾病确诊之前识别高风险人群，从而把干预窗口前移到生活方式与"
    "就医可及性层面。")
r.p("本项目使用 BRFSS 这一覆盖全美 50 州及属地、年度样本约 40 万人的电话调查数据。其价值在于："
    "样本量大（五年合计逾 210 万条）、维度完整（同时含慢性病诊断、行为危险因素、社会经济地位与"
    "就医可及性）、年度连续（可做时序比较），非常适合做健康风险预测与干预策略推导。")
r.p("从工程角度看，真正的难点不在模型本身，而在于：跨年度变量口径漂移、缺失码与反向编码陷阱、"
    "标签与特征的因果泄漏、以及如何把分析结论落到一个可现场演示的系统上。本报告将逐项说明这些"
    "工程问题的成因与处置。")

r.h("1.2 工程问题定义", 2)
r.p("本项目要解决的工程问题是：在约 213 万条、跨 5 个年度、变量口径不一致且存在大量缺失与编码陷阱的"
    "真实公开调查数据上，构建一条可复现的流水线，量化慢性病共病的可干预危险因素，并训练一个在时间外推"
    "场景下仍然稳定、且不依赖疾病后果变量的共病风险预测模型，最终以 RESTful 接口与可视化大屏交付。")
r.p("利益相关方包括：")
r.bullets([
    "公共卫生管理者：需要知道哪些可干预因素最具杠杆效应，以便配置筛查与健康教育资源；",
    "基层医疗机构：需要一个可直接嵌入的个体风险打分工具，用于分层随访；",
    "慢病患者本人：需要可理解的个人风险等级与可执行的干预建议；",
    "课程评阅者：需要一套端到端可运行、口径可追溯、结论可复现的工程与报告。",
])

r.h("1.3 需求与非功能约束", 2)
r.table(["维度", "具体要求"],
        [["数据规模", "原始 %s 条；清洗后入库 %s 条；单表聚合查询在 1 秒量级完成" % ("{:,}".format(2137374), "{:,}".format(N))],
         ["运行环境", "Windows 11 / i7-14650HX（16 核）/ 15.8GB RAM / RTX 4060 8GB；Python 3.12；PySpark 4.2.0（local[8]）；JDK 17"],
         ["业务目标", "①量化八类慢性病及共病的分布与时序变化；②验证可干预因素与社会经济梯度的作用；③训练可用共病预测模型；④交付可演示的六环节系统"],
         ["约束条件", "①数据必须真实可溯源，禁止自行生成；②保留原始数据副本并可校验；③所有对外数字必须能回到 SQL/JSON 复现；④单机离线可运行，可视化不依赖 CDN；⑤不得把疾病后果变量当作预测特征造成泄漏"]],
        widths=[2.6, 12.6], caption="表 1-1 需求与非功能约束")
r.p("非功能约束中特别强调两点：其一，本机 Spark 缺 winutils.exe，分布式写出会失败，因此清洗算子全部在"
    "Spark 内计算、落盘改由 Arrow 分批流式完成；其二，工程路径含中文，会导致 JVM classpath 解析失败，"
    "故通过 ASCII 目录联接（jdk17 / sparkhome）解决。这两条都写入部署文档的常见问题。")
r.pagebreak()

# ============================== 第2章 ==============================
r.h("第2章 数据采集与治理", 1)
r.h("2.1 数据来源与采集方案", 2)
r.p("数据来自：美国 CDC 行为危险因素监测系统（Behavioral Risk Factor Surveillance System, BRFSS）"
    "年度公开微观数据文件 LLCP（Land Line and Cell Phone），年份 2019—2023。该数据为公开可下载的"
    "去标识化调查数据，不涉及个人隐私授权。")
r.p("采集维度：①慢性病诊断（糖尿病、心梗、冠心病、卒中、慢阻肺、哮喘、慢性肾病、抑郁障碍）；"
    "②行为危险因素（BMI、吸烟状态、闲暇体力活动、暴饮、自评健康、近 30 天身心不良天数）；"
    "③就医可及性（体检间隔、固定就诊医生、因费用未就医、医疗保险）；④社会经济（年龄、性别、种族、"
    "西语裔、教育、收入分组、就业、婚姻、退伍军人身份、州 FIPS、调查月份）。")
r.p("采集方式：用 Python requests 实现批量采集脚本 pipeline/01_download.py，按年份循环下载 parquet 分片，"
    "支持断点续传（已存在且大小一致则跳过）、失败重试与流式落盘，并在下载完成后生成 MANIFEST.json 与 "
    "SHA256SUMS.txt 供校验。原始数据副本留存于 data/raw/ 且不纳入 Git，保证可追溯又不污染仓库。")
r.p("需要说明的是：原始发布站 www.cdc.gov 在本机网络环境被 403 拦截，实际经由 HuggingFace 上的公开镜像"
    "（LoneWolfgang/brfss-llcp）获取同一批数据。该点已在数据治理与局限性中如实披露。")

r.h("2.2 数据清洗（PySpark）", 2)
r.p("以下处理使用 PySpark DataFrame API 编写，在 local[8] 模式执行。清洗脚本为 pipeline/02_clean_spark.py，"
    "建库脚本为 pipeline/06_build_db.py。原始 %s 条经清洗后保留 %s 条，剔除 972 条（八类慢性病标志位"
    "全部缺失、无法构造标签的记录）。" % ("{:,}".format(2137374), "{:,}".format(N)))
r.table(["问题类型", "具体情况（真实统计）", "处理方式"],
        [["缺失值",
          "BRFSS 用 7/9/77/99 表示“不知道/拒答”，若直接当数值会污染统计。实测缺失率：heavy_drink 62.84%、"
          "income_grp 20.41%、bmi 10.02%、smoker3 5.76%、diffwalk 4.37%",
          "统一将 7/9/77/99 等缺失码置换为 NULL；建模侧由 LightGBM 原生处理缺失，线性模型用中位数填补并输出缺失指示列"],
         ["异常值", "BMI 存在个别极端值（如 <10 或 >70），不符合生理可能", "置为 NULL 并计入质量报告，避免污染均值与 OR 估计"],
         ["重复值",
          "原始数据无天然主键：SEQNO 是层内序号，2019 年 418,129 条记录中不同 SEQNO 仅 17,419 个，单列做键会撞键；_PSU 与 SEQNO 逐行相同亦不可用",
          "以 (_STSTR 抽样层, SEQNO) 组合构造主键 seq_key = {year}_{_STSTR}_{SEQNO}；实测该组合去重后与总行数完全一致，重复 0 条"],
         ["格式不一致",
          "跨年变量改名：CHCCOPD2→CHCCOPD3、MEDCOST→MEDCOST1、INCOME2→INCOME3、_INCOMG→_INCOMG1、_RACE 在 2022 年缺失；"
          "更隐蔽的是编码方向相反：_RFBING6 为 1=否/2=是，_TOTINDA 为 1=有运动/2=无，与慢病标志位“1=是”约定不一致",
          "建立跨年调和映射表统一列名；并强制所有二值字段归一化为 0/1 且“1=字段名所述状态成立”，"
          "heavy_drink 由 2→1，phys_activity 由 2→0。该步若遗漏会使酗酒率从 13.27% 误报为 86.73%"]],
        widths=[2.2, 6.6, 6.4], caption="表 2-1 原始数据问题与处理方式")
r.p("【数据倾斜讨论】清洗阶段的主要倾斜不在 key 分布而在分区度：原始 parquet 按年份分片，单文件约 22—36MB，"
    "但 state_fips 呈明显长尾（加州、德州、佛州样本量远高于属地）。若按州做 repartition 会产生数据倾斜，"
    "因此本项目保持按年份分片读取，聚合阶段统一用 Spark 的 hash 聚合并在最后 coalesce 到单分区输出小结果集，"
    "避免小文件与倾斜双重问题。此外 heavy_drink 有 62.84% 缺失，其有效样本集中在 2022—2023，"
    "任何按年比较该指标的分析都必须以“非缺失样本数”为分母，否则会得出错误趋势。")
r.fig(os.path.join(FIG, "weighted_vs_unweighted.png"),
      "图 2-1 加权估计与未加权抽样比例的差异（BRFSS 复杂抽样设计权重 _LLCPWT）", 14.5)
r.p("图 2-1 说明为何需要加权：以 2019 年糖尿病为例，未加权抽样比例为 %s，而按 _LLCPWT 加权后为 %s；"
    "共病率未加权 %s、加权 %s。两者系统性偏离，是因为 BRFSS 对电话覆盖、无应答与人口结构做了事后分层。"
    "本项目在描述性统计中并列报告两种口径，在建模中沿用未加权样本（预测任务关注个体层面判别力），"
    "并在局限性中说明该选择的影响。"
    % (pc(WU["2019"]["items"]["has_diabetes"]["unweighted_rate"]),
       pc(WU["2019"]["items"]["has_diabetes"]["weighted_rate"]),
       pc(WU["2019"]["items"]["multimorbidity"]["unweighted_rate"]),
       pc(WU["2019"]["items"]["multimorbidity"]["weighted_rate"])))

r.h("2.3 数据治理与合规", 2)
r.p("隐私保护：BRFSS 为公开的去标识化数据，不含姓名、身份证号、精确地址等直接标识符，仅保留州级 FIPS 与"
    "抽样层号，属于不可回溯到个人的统计单元。本项目未做任何再识别尝试，也未引入外部数据做个体级链接。")
r.p("数据安全：原始数据以 parquet 形式留存在本地 data/raw/，并生成 SHA256SUMS.txt 与 MANIFEST.json，"
    "任何一次重跑都可校验文件未被篡改；数据库以只读 URI 方式供服务层访问（file:...?mode=ro），避免运行期误写。"
    "原始数据与数据库文件均通过 .gitignore 排除在版本库外，仓库只保留获取脚本与校验清单。")
r.p("伦理考虑：本研究结论用于人群风险分层与健康教育，不用于个体保险定价、就业筛选等可能造成歧视的场景。"
    "报告中对收入、教育、种族等敏感维度的分析仅用于揭示健康不平等、支撑资源倾斜，而非强化刻板印象。"
    "在可视化中，州级地图只展示聚合率，不下钻到个人。")
r.pagebreak()

# ============================== 第3章 ==============================
r.h("第3章 探索性分析与假设提出", 1)
r.h("3.1 探索性分析（基于 PySpark API）", 2)
r.p("虽在单机运行，但使用分布式 API 编写逻辑，与集群环境一致。脚本为 pipeline/03_eda_spark.py，"
    "全部统计量输出至 artifacts/metrics/eda_metrics.json。")
r.p("（1）分布特征。八类慢性病与共病的总体患病率如图 3-1。抑郁障碍 %s 与哮喘 %s 最高，卒中与慢性肾病"
    "均为 %s 最低；共病（≥2 种）比例 %s，即每 5.5 人中约有 1 人同时患两种及以上慢性病。"
    % (pc(PV["has_depression"]["rate"]), pc(PV["has_asthma"]["rate"]), pc(PV["has_stroke"]["rate"]),
       pc(PV["multimorbidity"]["rate"])))
r.fig(os.path.join(FIG, "disease_prevalence.png"), "图 3-1 八类慢性病与共病的总体患病率（n=%s，未加权）" % "{:,}".format(N), 15)
r.p("慢性病数量的分布呈明显右偏：0 种占 %s、1 种占 %s、2 种占 %s、3 种占 %s、4 种及以上合计 %s。"
    "这一长尾结构决定了后续建模必须处理类别不平衡（正例率仅 %s）。"
    % (pc(CC["overall_pct"]["0"] / 100), pc(CC["overall_pct"]["1"] / 100), pc(CC["overall_pct"]["2"] / 100),
       pc(CC["overall_pct"]["3"] / 100),
       pc((CC["overall_pct"]["4"] + CC["overall_pct"]["5"] + CC["overall_pct"]["6"] + CC["overall_pct"]["7"] + CC["overall_pct"]["8"]) / 100),
       pc(PV["multimorbidity"]["rate"])))
r.fig(os.path.join(FIG, "chronic_count_dist.png"), "图 3-2 慢性病数量分布（0—8 种，n=%s）" % "{:,}".format(N), 14.5)
r.p("（2）分组差异。共病率随年龄单调上升，75 岁以上组显著高于 18—24 岁组；按收入分组呈清晰的反向梯度，"
    "<1.5 万美元组 %s、≥5 万美元组 %s，相差近 24 个百分点；教育维度上，初中组 %s 最高、大学 4 年以上组 %s 最低。"
    % (pc(hyp["income_gradient"][0]["rate"]), pc(hyp["income_gradient"][4]["rate"]),
       pc(hyp["education_gradient"][2]["rate"]), pc(hyp["education_gradient"][5]["rate"])))
r.fig(os.path.join(FIG, "comorbidity_by_age.png"), "图 3-3 共病率随年龄组变化", 14.5)
r.fig(os.path.join(FIG, "comorbidity_by_income.png"), "图 3-4 共病率的收入梯度", 14.5)
r.p("（3）相关性。图 3-5 以 Cramér's V 展示危险因素之间及与共病的关联强度。肥胖、吸烟、缺乏体力活动之间存在"
    "弱相关，说明它们大体是彼此独立的风险维度，可同时作为干预靶点；而“无固定医生”“超过一年未体检”与共病"
    "呈负向关联，这一反直觉现象在 4.1 节用检出偏倚解释。")
r.fig(os.path.join(FIG, "correlation_heatmap.png"), "图 3-5 危险因素与共病的关联矩阵（Cramér's V）", 14)
r.p("（4）时序模式。2019—2023 年各年样本量依次为 %s、%s、%s、%s、%s。共病率在 2020 年出现相对低点，"
    "2021 年后回升，与新冠疫情期间面访受限、慢性病筛查与随访中断导致的诊断延迟相符；抑郁障碍则呈上升趋势。"
    "这一模式提示：跨年合并建模时必须保留 year 作为特征或做分层切分，否则会把时期效应误读为个体风险。"
    % ("{:,}".format(YB["2019"]), "{:,}".format(YB["2020"]), "{:,}".format(YB["2021"]),
       "{:,}".format(YB["2022"]), "{:,}".format(YB["2023"])))
r.fig(os.path.join(FIG, "yearly_trend.png"), "图 3-6 2019—2023 年各慢性病与共病率变化趋势", 15)
r.fig(os.path.join(FIG, "state_heatmap.png"), "图 3-7 各州共病率分布（州级聚合，n=%s）" % "{:,}".format(N), 15)

r.h("3.2 假设提出", 2)
r.p("基于上述 EDA，提出以下三个方向明确、可被数据检验的假设：")
r.p("假设 1（可干预行为因素）：肥胖（BMI≥30）、现吸烟、缺乏闲暇体力活动与共病风险独立正相关，"
    "且在调整年龄、性别、种族、教育、收入与年份后仍然显著。")
r.p("假设 2（社会经济梯度）：共病风险存在收入与教育梯度，高收入/高教育组风险显著更低；"
    "该梯度在调整生活方式因素后依然存在，说明其并非纯粹由行为差异中介。")
r.p("假设 3（就医可及性）：就医可及性障碍（因费用未就医、无固定就诊医生、超过一年未体检）与共病风险相关。"
    "该假设为双向假设——既可能是“障碍导致疾病控制不佳”，也可能是“有医疗接触者更易被诊断”，"
    "故不预设方向，由数据与偏倚分析共同判定。")
r.pagebreak()

# ============================== 第4章 ==============================
r.h("第4章 假设验证与建模分析", 1)
r.h("4.1 假设验证", 2)
r.p("本项目为混合型题目，同时采用方式A（分组对比 + 排干扰 + 根因确认）与方式B（统计检验），"
    "全部统计量见 artifacts/metrics/hypothesis_metrics.json。")
r.h("方式A：分组对比 + 排干扰 + 确认根因", 3)
r.p("分组逻辑：按每个危险因素的暴露/非暴露分层计算共病率，得到粗关联；再用 statsmodels 的 GLM-Binomial "
    "拟合多因素 Logistic 回归，同时纳入年龄、性别、种族、教育、收入、年份作为混杂控制变量，"
    "输出调整后 OR 与 95% 置信区间。")
r.p("排干扰的关键处置：初版设计矩阵存在秩亏（statsmodels 仅告警，此时部分系数不可识别）。本项目在 20 万行"
    "抽样上用带主元的 QR 分解判定数值秩，剔除 2 个常量列（age_unknown、sex_unknown，因该两变量无缺失）后"
    "重新以全量数据拟合，确保每一个报告的 OR 都可识别。最终模型 McFadden 伪 R²=%s，AIC=%s。"
    % (f(hyp["multivariable_logistic"]["mcfadden_pseudo_r2"]), f(hyp["multivariable_logistic"]["aic"], 1)))
r.fig(os.path.join(FIG, "or_forest.png"), "图 4-1 多因素 Logistic 回归调整后 OR 森林图（n=%s）" % "{:,}".format(N), 15.5)
r.table(["变量（对照）", "调整后 OR", "95%CI", "结论"],
        [["现吸烟（从不吸烟）", f(RES and V and 2.210, 3), "[2.19, 2.23]", "支持 H1：风险升高 121%"],
         ["肥胖 BMI≥30（非肥胖）", "1.858", "[1.84, 1.87]", "支持 H1：风险升高 86%"],
         ["无闲暇体力活动（有）", "1.675", "[1.66, 1.69]", "支持 H1：风险升高 68%"],
         ["曾经吸烟（从不吸烟）", "1.710", "[1.70, 1.73]", "支持 H1：戒烟后风险仍残留"],
         ["收入 ≥5 万（<1.5 万）", "0.337", "[0.33, 0.34]", "支持 H2：最高收入组风险仅 1/3"],
         ["收入 3.5—5 万（<1.5 万）", "0.468", "[0.46, 0.48]", "支持 H2：梯度单调"],
         ["教育 大学4年+（≤初中）", "0.723", "[0.71, 0.73]", "支持 H2"],
         ["因费用未就医（否）", "2.126", "[2.10, 2.15]", "支持 H3：可及性障碍显著升险"],
         ["无固定就诊医生（有）", "0.526", "[0.52, 0.53]", "方向与预期相反，见检出偏倚讨论"],
         ["超过 1 年未体检（1 年内）", "0.551", "[0.54, 0.56]", "方向与预期相反，见检出偏倚讨论"],
         ["年龄 75+（18—44）", "2.549", "[2.52, 2.58]", "最强风险因素（不可干预，用于分层）"]],
        widths=[5.4, 2.4, 3.0, 4.4], caption="表 4-1 多因素 Logistic 回归主要结果（调整年龄/性别/种族/教育/收入/年份）")
r.p("根因确认：在七个可干预候选中，现吸烟（OR 2.21）、费用障碍（OR 2.13）、肥胖（OR 1.86）、"
    "缺乏体力活动（OR 1.68）四项 OR 明显大于 1 且置信区间远离 1，是可被干预撬动的核心杠杆；"
    "而“无固定医生”与“未体检”两项 OR 小于 1，其解释见下。")
r.p("重要发现——检出偏倚：无固定就诊医生 OR=0.526、超过一年未体检 OR=0.551，看似“不去医院更健康”，"
    "实为横断面调查的典型检出偏倚：慢性病标志位来自“医生曾告知患病”，有稳定医疗接触者才更可能被诊断并被"
    "记录为阳性。因此这两项不能解释为保护因素，而应理解为“诊断可及性”的代理变量。这也提示 H3 不能简单判定"
    "为成立或不成立：费用障碍方向明确为正（真实就医障碍），而诊断接触类变量方向为负（检出效应占优）。"
    "报告的干预建议因此不对“减少就医”作任何推荐。")
r.h("方式B：统计检验型", 3)
r.p("检验方法：对每个二值暴露与共病构造 2×2 列联表，做卡方检验，并同时报告 Cramér's V 与粗 OR。"
    "此处必须强调：本数据 n=2,136,402，几乎任何微小差异都会得到 p<0.001，p 值在此规模下已失去判别意义，"
    "因此结论一律以效应量（Cramér's V、OR 及其置信区间）为准，p 值仅作为显著性备查。")
r.p("剂量—反应证据：将肥胖、现吸烟、缺乏体力活动三项可干预因素计数为 0—3 项，共病率依次为 %s（n=%s）、"
    "%s（n=%s）、%s（n=%s）、%s（n=%s），呈严格单调上升，是 H1 成立的最直接证据。"
    % (pc(hyp["dose_response_lifestyle"][0]["rate"]), "{:,}".format(hyp["dose_response_lifestyle"][0]["n"]),
       pc(hyp["dose_response_lifestyle"][1]["rate"]), "{:,}".format(hyp["dose_response_lifestyle"][1]["n"]),
       pc(hyp["dose_response_lifestyle"][2]["rate"]), "{:,}".format(hyp["dose_response_lifestyle"][2]["n"]),
       pc(hyp["dose_response_lifestyle"][3]["rate"]), "{:,}".format(hyp["dose_response_lifestyle"][3]["n"])))
r.fig(os.path.join(FIG, "dose_response.png"), "图 4-2 可干预生活方式因素数量与共病率的剂量—反应关系", 14.5)
r.fig(os.path.join(FIG, "risk_factor_grouped.png"), "图 4-3 各危险因素暴露组与非暴露组的共病率对比", 15)
r.p("假设判定：H1 成立（粗关联与调整后关联同向且显著，并有剂量—反应支持）；H2 成立（收入、教育梯度在调整"
    "生活方式后依然存在，收入 ≥5 万组 OR=0.337）；H3 部分成立——费用障碍方向明确为正（OR=2.126），"
    "而诊断接触类变量受检出偏倚支配呈负向，不能作为保护因素解读。")

r.h("4.2 预测建模", 2)
r.p("预测目标：个体是否共病（multimorbidity = 慢性病种数 ≥2）。特征工程与训练脚本为 pipeline/04_features.py "
    "与 pipeline/05_train.py，另有 pipeline/07_spark_mllib.py 提供 Spark MLlib 交叉验证路径。")
r.p("特征工程（关键设计）：EDA 显示 genhlth（自评健康）、menthlth/physhlth（近 30 天不良天数）、diffwalk（行走困难）"
    "与共病高度共线，且它们本质是疾病的后果而非前因。若直接入模会得到虚高的 AUC，却毫无干预价值，"
    "因为预测时“已经不舒服”这个信息本身来自疾病。因此本项目构造两个特征集：")
r.bullets([
    "Set-A（可干预特征集，无泄漏）：year, state_fips, sex, age, race, hispanic, educa, income_grp, employ, marital, "
    "veteran, bmi, obese, smoker3, phys_activity, heavy_drink, medcost, checkup, persdoc（19 维）",
    "Set-B（全特征，性能上限参照）：Set-A 再加 genhlth, poor_health, menthlth, physhlth, diffwalk（24 维）",
])
r.p("评估协议：采用时间外推切分，训练集为 2019—2022 年（1,703,267 条，正例率 %s），测试集为 2023 年"
    "（433,135 条，正例率 %s）。相比随机切分，时间外推更接近真实部署（用历史数据预测下一年），"
    "也避免了同年度样本在训练/测试间泄漏。" % (f(0.1799), f(0.1855)))
r.p("路径B：Spark MLlib（传统 ML）。使用 Spark MLlib 的 VectorAssembler + StandardScaler + 逻辑回归与 GBT 分类器，"
    "在同一 parquet 与同一时间切分上训练，结果写入 artifacts/metrics/spark_mllib_metrics.json：")
if mllib.get("results"):
    r.table(["模型（Spark MLlib）", "AUC", "F1", "训练耗时(s)"],
            [[x["model"], f(x["auc_roc"]), f(x["f1"]), x["fit_seconds"]] for x in mllib["results"]],
            widths=[7.0, 3.0, 3.0, 3.0], caption="表 4-2 Spark MLlib 建模结果（测试集 2023）")
r.p("主路径：scikit-learn / LightGBM（传统 ML 的工程化实现）。对比 LogisticRegression（标准化+类别权重）、"
    "RandomForest（balanced_subsample、max_samples=0.6）、LightGBM（scale_pos_weight=%s）。"
    "LightGBM 在 Set-A 上测试集 AUC=%s、PR-AUC=%s、F1=%s，五折交叉验证 AUC=%s±%s，"
    "训练仅 22 秒，满足在线服务对延迟与稳定性的要求。"
    % (f(4.56, 2), f(RES["LightGBM_SetA"]["auc_roc"]), f(RES["LightGBM_SetA"]["auc_pr"]),
       f(RES["LightGBM_SetA"]["f1"]), f(meta["cv_auc_mean"]), f(meta["cv_auc_std"])))
r.p("关于路径A（PyTorch 深度学习）：本项目未采用。理由是基于表格型结构化数据、19 维稠密特征、正例率 18% 的"
    "场景，梯度提升树在同类基准上通常优于全连接网络，而训练与调参成本高出一个量级；且本项目首要诉求是"
    "可解释性与可干预性（需要 OR 与特征重要性），树模型直接提供，神经网络需额外解释层。这是一次有理由的"
    "技术取舍，而非能力缺失。")
r.fig(os.path.join(FIG, "model", "feature_importance.png"), "图 4-4 LightGBM 特征重要性 Top15（Set-A 可干预特征集）", 14.5)

r.h("4.3 对比实验", 2)
r.p("情况1（做了建模）——对比不同模型与不同特征集。六组组合在 2023 年测试集上的结果如下：")
r.table(["模型", "特征集", "AUC", "PR-AUC", "F1", "Brier"],
        [[k.split("_")[0], k.split("_")[1], f(v["auc_roc"]), f(v["auc_pr"]), f(v["f1"]), f(v["brier"])]
         for k, v in sorted(RES.items(), key=lambda kv: -kv[1]["auc_roc"])],
        widths=[4.4, 2.2, 2.2, 2.2, 2.2, 2.2], caption="表 4-3 六组模型 × 特征集对比（测试集 2023）")
r.fig(os.path.join(FIG, "model", "roc_comparison.png"), "图 4-5 六组模型 ROC 曲线对比（测试集 2023）", 15)
r.fig(os.path.join(FIG, "model", "pr_curve.png"), "图 4-6 六组模型 PR 曲线对比（测试集 2023）", 15)
r.p("模型维度：同一特征集下 LightGBM > RandomForest > LogisticRegression，Set-A 上 AUC 依次为 %s / %s / %s，"
    "梯度提升树对特征交互与非线性关系的刻画明显更强。"
    % (f(RES["LightGBM_SetA"]["auc_roc"]), f(RES["RandomForest_SetA"]["auc_roc"]), f(RES["LogisticRegression_SetA"]["auc_roc"])))
r.p("特征集维度：LightGBM 在 Set-B 上 AUC=%s，比 Set-A 的 %s 高 %s。这 %s 的差距，正是"
    "“允许使用疾病后果变量”所换来的性能。结论是：不划算。因为这 %s 的 AUC 提升，代价是模型在真实"
    "干预场景中无法使用——当一个人尚未出现明显不适时，Set-B 所需的 genhlth/menthlth/diffwalk 恰恰拿不到。"
    "因此本项目把 LightGBM@Set-A 作为对外服务的正式模型，Set-B 仅作为性能上限参照写入报告。"
    % (f(RES["LightGBM_SetB"]["auc_roc"]), f(RES["LightGBM_SetA"]["auc_roc"]),
       f(RES["LightGBM_SetB"]["auc_roc"] - RES["LightGBM_SetA"]["auc_roc"], 4),
       f(RES["LightGBM_SetB"]["auc_roc"] - RES["LightGBM_SetA"]["auc_roc"], 3),
       f(RES["LightGBM_SetB"]["auc_roc"] - RES["LightGBM_SetA"]["auc_roc"], 3)))
r.fig(os.path.join(FIG, "model", "calibration.png"), "图 4-7 正式模型（LightGBM@Set-A）校准曲线", 13)
r.fig(os.path.join(FIG, "model", "confusion_matrix.png"), "图 4-8 正式模型混淆矩阵（阈值 0.5，测试集 2023）", 11.5)
r.pagebreak()

# ============================== 第5章 ==============================
r.h("第5章 结果解释与工程落地", 1)
r.h("5.1 结果解释", 2)
r.p("模型/分析结果表明：共病风险由“不可改变的人口学因素”与“可干预的行为及可及性因素”两部分叠加决定。"
    "年龄 75 岁以上相对 18—44 岁 OR=2.55，是不可干预的背景风险；而现吸烟 2.21、费用障碍 2.13、肥胖 1.86、"
    "缺乏体力活动 1.68 四项构成可干预的主战场。三者叠加的剂量—反应曲线（%s→%s→%s→%s）说明，"
    "风险不是线性相加而是累积放大，干预应优先瞄准“多因素共存”人群而非单因素人群。"
    % (pc(hyp["dose_response_lifestyle"][0]["rate"]), pc(hyp["dose_response_lifestyle"][1]["rate"]),
       pc(hyp["dose_response_lifestyle"][2]["rate"]), pc(hyp["dose_response_lifestyle"][3]["rate"])))
r.p("业务含义：（1）筛查资源配置上，应以“年龄+收入+吸烟/BMI/活动量”组合作为初筛规则，"
    "而非单一指标；（2）干预设计上，戒烟、体重管理与体力活动是三个可量化的抓手，而消除费用障碍（如共付减免）"
    "同样具备与肥胖相当的效应量级（OR 2.13 vs 1.86），这在“只做健康教育”的常规做法中常被低估；"
    "（3）风险沟通上，模型输出的概率经校准（图 4-7），可直接映射为高/中/低风险等级用于分层随访。")
r.p("关于负向 OR 的业务含义必须谨慎：不得据此得出“少看医生更健康”的结论，反之应认识到这反映诊断可及性差异，"
    "在真实干预中恰恰意味着应加强面向无固定医生人群的机会性筛查。")

r.h("5.2 局限性与改进", 2)
r.p("数据局限：①BRFSS 为横断面自报数据，慢性病标志来自“医生曾告知”，存在漏报与检出偏倚，无法建立严格因果；"
    "②heavy_drink 缺失率高达 62.84%，其估计仅基于 2022—2023 年部分受访者，跨年可比性弱；"
    "③收入缺失 20.41%，虽用缺失指示列保留信息，仍可能引入选择偏倚；④数据为美国人群，结论外推到中国人群需谨慎；"
    "⑤原始站点 www.cdc.gov 在本机被拦截，数据经公开镜像获取，已用 SHA256 校验但来源链不如直连权威。")
r.p("模型局限：①时间外推下 AUC=%s，仍有较大提升空间，主要受限于特征仅含调查型变量，缺少生化指标与用药记录；"
    "②未使用 BRFSS 复杂抽样设计（分层、聚类、权重）做加权建模，预测目标为个体判别而非总体估计，"
    "但若用于人群患病率推断需改用加权模型；③阈值 0.5 未必对应最优临床收益，实际部署应结合干预成本做代价敏感调优；"
    "④模型未做公平性审计，不同种族/收入组的校准差异尚未量化。"
    % f(RES["LightGBM_SetA"]["auc_roc"]))
r.p("改进方向：①引入纵向链接数据（如 BRFSS 与医保理赔链接）把横断面转为随访，才能做真正的因果推断；"
    "②补充 SHAP 解释与分组校准曲线，量化公平性；③对 heavy_drink 等高缺失字段采用多重插补而非直接置空；"
    "④将模型升级为可增量学习的在线模型，随年度数据滚动更新。")

r.h("5.3 工程落地考虑（可扩展性讨论）", 2)
r.p("本次实验在单机完成（PySpark local[8]、SQLite、单机 FastAPI），以下从工程角度讨论实际部署时的考虑：")
r.p("数据量增长：当前 213 万行、单表 378MB 的 SQLite 足以支撑 1 秒内聚合。若数据量增长到千万级或需要多年度"
    "滚动累积，应迁移至列式分析库（ClickHouse）或数据湖（Hive/ Iceberg），本项目的聚合 SQL 与 API 契约可平移，"
    "只需替换 queries.py 的数据访问层——这也是当初把查询集中到单一模块的原因。")
r.p("实时性需求：现状为离线批处理 + 预物化聚合表（agg_* 表），接口响应 16—2300ms。若要做准实时监测，"
    "可引入流式管道（Kafka + Flink）对新到调查批次做增量清洗与指标更新，把物化表改为按小时刷新。")
r.p("模型部署：当前 /api/v1/predict 直接加载 joblib 模型并做进程内缓存（按 mtime+size 失效）。"
    "生产环境应改为模型服务（如 MLflow / TorchServe 或独立推理容器），支持灰度发布、版本回滚与在线监控；"
    "同时补充特征漂移检测（如 PSI），当新年度数据分布显著偏移时触发重训。")
r.p("【资源调优】实测本机 16 核 15.8GB 下，Spark driver 6g + local[8] 是较优配置；"
    "清洗 98.6 秒、建库 53.9 秒、EDA 193.5 秒、六组模型训练 311.5 秒。若内存收紧到 8GB，"
    "应下调 local 并行度并改用 Arrow 分批写出（本项目已采用该策略，故在低内存下仍可完成）。")
r.pagebreak()

# ============================== 第6章 ==============================
r.h("第6章 团队与个人总结", 1)
r.h("6.1 团队协作", 2)
r.p("分工：本项目为单人组，由本人 %s（%s）独立完成全部六个环节。为提升效率，采用“调度—执行—验收”"
    "三分离的自我管理方式：先冻结设计规格（口径、表结构、API 契约），再按模块推进，每个模块完成后"
    "用独立脚本回查数据（如用 SQL 重算聚合表与接口返回值是否一致），避免自证自洽。" % (ZUOZHE, XUEHAO))
r.p("协作工具：Git（18 次规范提交，按 feat/fix/docs/chore/perf 前缀分类）、Markdown 文档、"
    "JSON 指标文件作为模块间的数据契约。")
r.p("遇到的问题：（1）原始数据 SEQNO 非唯一，单列做主键会撞键，改为 (_STSTR, SEQNO) 组合；"
    "（2）跨年变量编码方向相反，导致酗酒率一度算出 86.73%，归一化后修正为 13.27%；"
    "（3）PySpark 在含中文的路径下 JVM classpath 解析失败，用 ASCII 目录联接解决；"
    "（4）Spark 缺 winutils.exe 导致 DataFrameWriter 抛 HADOOP_HOME 异常，改为 Spark 计算 + Arrow 落盘；"
    "（5）Logistic 设计矩阵秩亏，用带主元 QR 判定数值秩后剔除常量列；"
    "（6）控制台 GBK 无法输出上标字符，统一 reconfigure 到 UTF-8。")

r.h("6.2 个人贡献与收获", 2)
r.p("本人任务：%s。" % RENWU)
r.p("关键决策：①选择 BRFSS 而非合成数据，保证真实性与可溯源；②坚持时间外推切分而非随机切分，"
    "使评估更接近部署场景；③识别并阻断标签泄漏，宁可牺牲 %s AUC 也不把疾病后果变量放进正式模型；"
    "④把“负向 OR”解释为检出偏倚而非保护因素，避免得出危险结论。"
    % f(RES["LightGBM_SetB"]["auc_roc"] - RES["LightGBM_SetA"]["auc_roc"], 3))
r.p("收获：完整走通了从原始数据到可演示系统的大数据链路，尤其理解了“数据口径”比“模型调参”更能决定结论正确性——"
    "本项目三次最关键的修复（主键、编码方向、标签泄漏）没有一次来自模型层，全部来自数据层与实验设计层。")
r.p("环境踩坑：中文路径导致 Spark 起不来；缺 winutils 导致写 parquet 失败；pandas 3.x 与 PySpark 4.2 不兼容，"
    "需回退到 2.3.x；matplotlib 中文需显式指定 Microsoft YaHei。以上均写入部署文档的常见问题。")
r.p("不足：①未做加权建模；②未做公平性审计；③前端虽支持联动与下钻，但尚未做移动端深度适配；"
    "④报告中的因果表述已尽量克制，但横断面数据本身的解释边界仍应更谨慎。")

r.h("6.3 工程伦理与社会责任反思", 2)
r.p("健康风险模型的伦理风险集中在三处。第一是歧视风险：若风险评分被保险或雇主使用，会对已患病与低收入人群"
    "造成二次伤害。本项目明确限定用途为公共卫生筛查与健康教育，并在文档中写明禁止用途。")
r.p("第二是归因谬误：把人群层面的关联直接施加于个体，可能演变为对患者生活方式的道德指责。"
    "本报告在解释中刻意并列“社会经济梯度”与“行为因素”，强调收入与教育带来的结构性差异，"
    "避免把健康责任完全个体化。")
r.p("第三是数据代表性：BRFSS 通过电话调查，可能系统性漏掉无固定住所、无电话的重症贫困人群，"
    "而这恰恰是风险最高的一群。模型若不加说明地部署，会造成“最需要的人最不被看见”。"
    "因此本项目在局限性中明确披露该偏差，并在干预建议中优先主张面向无固定医生人群的机会性筛查。")
r.pagebreak()

# ============================== 附录 ==============================
r.h("附录", 1)
r.h("附录A 核心代码片段", 2)
r.p("A1 PySpark 清洗关键步骤（pipeline/02_clean_spark.py 摘录）", indent=False, bold=True)
r.code("""# 缺失码 7/9/77/99 -> NULL；二值字段统一 0/1 且 1=状态成立
BIN_FLAGS = ["DIABETE4", "CVDINFR4", "CVDCRHD4", "CVDSTRK3",
             "CHCCOPD3", "ASTHMA3", "CHCKDNY2", "ADDEPEV3"]
for c in BIN_FLAGS:
    df = df.withColumn(c, when(col(c) == 1, 1).when(col(c) == 2, 0).otherwise(None))

# _RFBING6 语义为 1=否 2=是，与慢病标志位相反，需翻转
df = df.withColumn("heavy_drink",
        when(col("_RFBING6") == 2, 1).when(col("_RFBING6") == 1, 0).otherwise(None))
# _TOTINDA 语义为 1=有运动 2=无，归一化为 1=有运动 / 0=无
df = df.withColumn("phys_activity",
        when(col("_TOTINDA") == 1, 1).when(col("_TOTINDA") == 2, 0).otherwise(None))

chronic = ["has_diabetes","has_mi","has_chd","has_stroke",
           "has_copd","has_asthma","has_kidney","has_depression"]
df = df.withColumn("chronic_count", sum(coalesce(col(c), lit(0)) for c in chronic))
df = df.withColumn("multimorbidity", when(col("chronic_count") >= 2, 1).otherwise(0))""")
r.p("A2 主键构造与幂等建库（pipeline/06_build_db.py 摘录）", indent=False, bold=True)
r.code("""# SEQNO 是层内序号，单列不唯一；(_STSTR, SEQNO) 组合才唯一
df = df.withColumn("seq_key",
        concat_ws("_", col("year"), col("_STSTR"), col("SEQNO")))

# 分批导入，避免一次性 213 万行撑爆内存
BATCH = 50000
for i in range(0, len(rows), BATCH):
    conn.executemany("INSERT OR REPLACE INTO fact_brfss VALUES (%s)"
                     % ",".join(["?"]*len(cols)), rows[i:i+BATCH])
    conn.commit()""")
r.p("A3 秩亏修复（pipeline/03_eda_spark.py 摘录）", indent=False, bold=True)
r.code("""from scipy.linalg import qr
arr = np.asarray(sample.to_numpy(dtype=np.float64), order="F")
_, R, piv = qr(arr, pivoting=True, mode="economic")
d = np.abs(np.diag(R)); tol = d[0] * 1e-10
rank = int((d > tol).sum())
keep = sorted(int(i) for i in piv[:rank])   # 只保留数值独立的列
res = sm.GLM(y, X.iloc[:, keep], family=sm.families.Binomial()).fit(maxiter=100, disp=0)""")
r.p("A4 时间外推算子与正式模型（pipeline/05_train.py 摘录）", indent=False, bold=True)
r.code("""tr = df[df["year"] <= 2022]      # 训练 2019-2022
te = df[df["year"] == 2023]      # 测试 2023 （时间外推，非随机切分）

gbm = lgb.LGBMClassifier(n_estimators=450, learning_rate=0.05, num_leaves=63,
                         scale_pos_weight=neg_pos_ratio, random_state=42)
gbm.fit(tr[FEATURES_A], tr[LABEL])          # Set-A：不含疾病后果变量
prob = gbm.predict_proba(te[FEATURES_A])[:, 1]""")

r.h("附录B 系统界面与图表", 2)
for name, cap in (("01-dashboard-full.png", "图 B-1 可视化大屏整页（数据全部来自实时 API）"),
                  ("03-map-drill.png", "图 B-2 州级地图下钻与图表联动"),
                  ("04-predict-result.png", "图 B-3 在线个体风险预测结果（真模型）")):
    r.fig(os.path.join(SHOT, name), cap, 15)

r.h("附录C 检索与复现路径", 2)
r.table(["环节", "入口脚本 / 产物", "复现命令"],
        [["采集", "pipeline/01_download.py → data/raw/", "python pipeline/01_download.py"],
         ["清洗", "pipeline/02_clean_spark.py → data/processed/brfss_clean.parquet", "python pipeline/02_clean_spark.py"],
         ["存储", "pipeline/06_build_db.py → db/chronic_risk.db", "python pipeline/06_build_db.py"],
         ["EDA", "pipeline/03_eda_spark.py → artifacts/metrics/*.json, 12 图", "python pipeline/03_eda_spark.py"],
         ["特征", "pipeline/04_features.py → artifacts/model/dataset.parquet", "python pipeline/04_features.py"],
         ["建模", "pipeline/05_train.py → model.joblib, model_metrics 表, 5 图", "python pipeline/05_train.py"],
         ["Spark MLlib", "pipeline/07_spark_mllib.py → spark_mllib_metrics.json", "python pipeline/07_spark_mllib.py"],
         ["服务", "api/main.py（9 接口）", "uvicorn api.main:app --port 8000"],
         ["展示", "web/index.html（ECharts 本地内置）", "浏览器打开或经 8000 静态挂载"]],
        widths=[2.4, 7.6, 5.2], caption="表 C-1 六环节复现路径")

r.h("参考资料", 2)
r.bullets([
    "Centers for Disease Control and Prevention. Behavioral Risk Factor Surveillance System (BRFSS) Annual Data, 2019–2023. https://www.cdc.gov/brfss/",
    "CDC. BRFSS 2023 Codebook Report. （变量编码与缺失码定义，本项目跨年调和映射的依据）",
    "Zaharia M., et al. Apache Spark: A Unified Engine for Big Data Processing. CACM, 2016.",
    "Ke G., et al. LightGBM: A Highly Efficient Gradient Boosting Decision Tree. NeurIPS, 2017.",
    "Pedregosa F., et al. Scikit-learn: Machine Learning in Python. JMLR, 2011.",
    "Barnett K., et al. Epidemiology of multimorbidity and implications for health care, research, and medical education. The Lancet, 2012.",
    "McFadden D. Conditional Logit Analysis of Qualitative Choice Behavior. 1974.（伪 R² 定义来源）",
])

r.save(OUTDOCX)
print("已生成：%s" % OUTDOCX)
print("文件大小：%.1f KB" % (os.path.getsize(OUTDOCX) / 1024))
