# 基于 BRFSS 大数据的慢性病患者健康风险预测与干预分析

> 课程：大数据分析课程设计　|　署名：**许宇翔 / 20240517108**
> 数据：美国 CDC **BRFSS**（Behavioral Risk Factor Surveillance System）LLCP 年度微观数据 2019–2023 五年合并，**2,137,374 条**
> 技术栈：PySpark 4.2（清洗 + EDA）· scikit-learn / LightGBM（建模）· SQLite（存储）· FastAPI 0.146（后端）· ECharts（前端）

本项目把"采集 → 存储 → 挖掘 → 后端 → 前端 → 可视化"六个环节做成一条**可复现的数据流水线**：
PySpark 负责 213 万行的清洗与探索性分析，scikit-learn/LightGBM 负责共病（multimorbidity）与糖尿病风险建模，
结果落进 SQLite，由 FastAPI 以 RESTful 接口对前端与在线预测开放。

---

## 一、六个环节与架构

```text
 ┌──────────────────────────────────────────────────────────────────────────┐
 │ ① 数据采集  pipeline/01_download.py                                       │
 │    HF 镜像下载 LLCP2019–2023 parquet（5 个文件、2,137,374 行）+ 字典       │
 │    落 data/raw/，生成 MANIFEST.json 与 SHA256SUMS.txt（可校验、可重建）    │
 └───────────────────────────────┬──────────────────────────────────────────┘
                                 ▼
 ┌──────────────────────────────────────────────────────────────────────────┐
 │ ② 数据存储  pipeline/02_clean_spark.py → 06_build_db.py                   │
 │    PySpark 统一跨年变量、缺失码 7/9/77/99 → NULL、BMI 异常剔除             │
 │    产物 data/processed/brfss_clean.parquet + model_dataset.parquet        │
 │    SQLite db/chronic_risk.db：fact_brfss（明细）+ dim_* + agg_* + 审计表   │
 └───────────────────────────────┬──────────────────────────────────────────┘
                                 ▼
 ┌──────────────────────────────────────────────────────────────────────────┐
 │ ③ 数据挖掘  pipeline/03_eda_spark.py · 04_features.py · 05_train.py       │
 │    EDA 图表 → artifacts/figures/；特征工程 → 模型数据集                    │
 │    LightGBM / 逻辑回归对比 → artifacts/metrics/ 与 artifacts/model/        │
 └───────────────────────────────┬──────────────────────────────────────────┘
                                 ▼
 ┌──────────────────────────────────────────────────────────────────────────┐
 │ ④ 后端服务  api/  ★ 本 README 主要覆盖的模块                              │
 │    FastAPI + Uvicorn，9 个契约接口，统一信封 + X-Response-Time           │
 │    只读 SQLite 聚合，数字全部来自库；joblib 热加载模型做在线预测           │
 └───────────────────────────────┬──────────────────────────────────────────┘
                                 ▼
 ┌──────────────────────────────────────────────────────────────────────────┐
 │ ⑤ 前端页面  web/index.html + app.js + style.css                           │
 │    ECharts 大屏，全部数据来自 http://127.0.0.1:8000/api/v1/*               │
 └───────────────────────────────┬──────────────────────────────────────────┘
                                 ▼
 ┌──────────────────────────────────────────────────────────────────────────┐
 │ ⑥ 可视化交付  docs/ + 课程设计报告 docx + 答辩 PPT                         │
 └──────────────────────────────────────────────────────────────────────────┘
```

## 二、目录说明

```text
慢性病患者健康风险预测与干预/
├── README.md                 本文件：简介、架构、快速开始、数据来源与合规
├── requirements.txt          真实依赖版本（取自本机 venv 的 pip freeze）
├── .gitignore                排除原始数据/数据库/模型二进制等可重建产物
├── api/                      后端服务（本模块）
│   ├── main.py               FastAPI 应用：9 个契约接口 + 在线预测
│   ├── contract.py           统一响应信封、错误码、异常处理器、X-Response-Time
│   └── queries.py            SQLite 只读聚合查询层（参数化、缺库降级）
├── tests/                    pytest 后端用例（30 个，内存临时库，不碰交付库）
│   ├── conftest.py           夹具：样例库 / 空库 / 缺库 / TestClient
│   ├── db_fixture.py         按规格第 4 节建表 + 确定性样例数据
│   ├── test_envelope.py      信封结构、耗时头、404、openapi 路径注册
│   ├── test_endpoints.py     9 接口取数与空库/缺库边界
│   └── test_predict.py       模型缺失(1001)、参数校验(400)、真实模型推理
├── pipeline/                 数据流水线脚本（采集→清洗→EDA→特征→训练→建库）
├── data/raw/                 原始 parquet + MANIFEST + SHA256SUMS（**不入库**）
├── data/processed/           清洗后 parquet（**不入库**，可由 pipeline 重建）
├── db/chronic_risk.db        SQLite 交付库（**不入库**，由 06_build_db.py 重建）
├── artifacts/figures/        图表；artifacts/metrics/ 指标；artifacts/model/ 模型
├── web/                      前端页面（ECharts）
├── docs/                     部署说明.md、接口文档.md、数据字典.md、数据质量报告.md
└── scripts/start_api.ps1     一键启动后端（PowerShell）
```

## 三、快速开始

> 全部命令在**工程根目录**执行：`cd "D:\期末作业\慢性病患者健康风险预测与干预"`

### 1) 建环境

```powershell
python -m venv D:\期末作业\.venv
D:\期末作业\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 2) 设置 PySpark 运行环境（只有跑管道时需要）

```powershell
$env:JAVA_HOME = "D:\jdk17"
$env:SPARK_HOME = "D:\sparkhome"
$env:PYSPARK_PYTHON = "D:\期末作业\.venv\Scripts\python.exe"
```

### 3) 跑数据流水线（下载 → 清洗 → EDA → 特征 → 训练）

```powershell
D:\期末作业\.venv\Scripts\python.exe pipeline\run_all.py
```

### 4) 建库（生成 db/chronic_risk.db）

```powershell
D:\期末作业\.venv\Scripts\python.exe pipeline\06_build_db.py
```

### 5) 启服务（端口固定 8000）

```powershell
D:\期末作业\.venv\Scripts\python.exe -m uvicorn api.main:app --host 0.0.0.0 --port 8000
# 或： powershell -ExecutionPolicy Bypass -File scripts\start_api.ps1
```

- 健康检查 <http://127.0.0.1:8000/api/v1/health>（应返回 `status=ok` 与真实 `factRows`）
- 交互式接口文档 <http://127.0.0.1:8000/docs>　|　接口清单 <http://127.0.0.1:8000/openapi.json>

### 6) 开前端

直接用浏览器打开 `web/index.html`（后端已开 CORS）；若浏览器限制本地文件，可执行
`D:\期末作业\.venv\Scripts\python.exe -m http.server 5500 -d web` 后访问 <http://127.0.0.1:5500/index.html>。

### 7) 跑后端测试

```powershell
D:\期末作业\.venv\Scripts\python.exe -m pytest tests -q     # 期望：30 passed
```

## 四、后端接口一览

统一信封：`{"code":0,"message":"ok","data":...,"traceId":"<uuid>","timestamp":<ms>}`，
每个响应带 `X-Response-Time`（毫秒）与 `X-Trace-Id`。

| # | 方法 | 路径 | 用途 |
|---|---|---|---|
| 1 | GET | /api/v1/health | 健康检查（DB 连接 + 真实行数；缺库返回 degraded 而非崩溃） |
| 2 | GET | /api/v1/overview | 总览 KPI（总样本、年份跨度、共病率、人均慢病数） |
| 3 | GET | /api/v1/chronic/prevalence?year=&state= | 八种慢病患病率 |
| 4 | GET | /api/v1/trend?metric= | 指标年度趋势（15 个可选指标） |
| 5 | GET | /api/v1/risk/factors?year= | 9 项可干预危险因素暴露率（key 与库表 agg_risk_factor 一一对应） |
| 6 | GET | /api/v1/risk/stratify | 风险分层分布（慢病数分布 / 等级 / 年龄组） |
| 7 | GET | /api/v1/geo/states?metric= | 州级指标（供地图） |
| 8 | GET | /api/v1/model/metrics | 模型指标与对比 |
| 9 | POST | /api/v1/predict | 在线个体共病风险预测（joblib 模型） |

错误码：`400` 参数校验失败 · `404` 路径不存在 · `1001` 模型未就绪 · `1002` 预测失败 · `1003` 数据库未就绪 · `500` 兜底。
**后端无鉴权、无默认账号**，仅用于课程演示，请勿直接暴露到公网。

细节见 [docs/接口文档.md](docs/接口文档.md)（含真实响应示例与口径附录）、[docs/部署说明.md](docs/部署说明.md)（含 JAVA_HOME/SPARK_HOME 与中文路径问题处理）。

## 五、数据来源与合规声明

- **来源**：美国 CDC 的 BRFSS 公开年度微观数据，原始发布页 www.cdc.gov/brfss。
  本项目通过 HuggingFace 镜像 `LoneWolfgang/brfss-llcp` 获取同一批公开数据
  （`https://huggingface.co/datasets/LoneWolfgang/brfss-llcp/resolve/main/data/LLCP{YYYY}.parquet`），
  五年行数与官方发布量级一致：418,268 / 401,958 / 438,693 / 445,132 / 433,323 = **2,137,374**。
  由于本机访问 cdc.gov 被 403 拦截，报告中已如实写明"经镜像获取同一批公开数据"这一事实。
- **清洗后入库**：当前交付库 `fact_brfss` 共 **2,136,402** 行（原始 2,137,374 − 972 行，
  差额来自清洗规则与主键唯一性约束，逐条原因见 docs/数据质量报告.md），
  `/api/v1/health` 的 `data.factRows` 即为此实时行数。
- **合规**：BRFSS 为**去标识化**公开统计数据，不含姓名、住址、证件号等个人身份信息，可自由用于研究与教学；
  本项目不对个体做任何形式的再识别尝试，不用于商业用途。
- **原始数据不入库**：`data/raw/` 已在 `.gitignore` 中排除。重建方式：

```powershell
# 方式A（推荐）：跑采集脚本，自带 SHA256 校验与 MANIFEST 生成
D:\期末作业\.venv\Scripts\python.exe pipeline\01_download.py
# 方式B：手工把 LLCP2019..2023.parquet 放入 data/raw/ 后，用脚本复核
D:\期末作业\.venv\Scripts\python.exe pipeline\01_download.py --verify
```

- **可重建产物**：`data/processed/*.parquet`、`db/chronic_risk.db`、`artifacts/model/*.joblib`、
  `artifacts/figures/*.png` 均由流水线生成，因此同样不纳入版本库（见 .gitignore）。

## 六、口径速查（与 _设计规格.md 一致）

| 口径 | 定义 |
|---|---|
| 慢性病标志位 | 8 个：糖尿病、心梗、冠心病、卒中、慢阻肺、哮喘、慢性肾病、抑郁；1=是 / 2=否，7、9 等缺失码 → NULL |
| chronic_count | 8 个标志位之和（NULL 记 0；8 项全 NULL 则该行标签不可用） |
| 主标签 multimorbidity | chronic_count ≥ 2（共病） |
| BMI | `_BMI5/100`，<10 或 >70 视为异常 → NULL |
| 二值字段编码 | 统一 0/1 且 **1 = 状态成立**（`heavy_drink` 1=酗酒、`phys_activity` 1=有运动，故"无运动"暴露取 0）；有序分类（`smoker3` / `genhlth` / `checkup` / `persdoc`）保持原码，如 `checkup=8` 才是"从未体检" |
| 主键 | `seq_key = f"{year}_{_STSTR}_{SEQNO}"`（**SEQNO 仅在层内唯一**：实测 2019 年 418,268 行只有 17,419 个不同 SEQNO，必须带 _STSTR 才唯一） |

## 七、已知限制

- 依赖 HF 镜像而非 CDC 直连，若镜像下线需改用其他公开来源；行数与变量语义以官方 codebook 为准。
- 横断面调查数据只能刻画**关联**，不能作为因果推断依据；在线预测输出的是共病概率，不是诊断结论。
- SQLite 单机聚合：`/geo/states`、`/risk/stratify` 首次请求需全表扫描（213 万行约数秒），服务端已内置 30 秒聚合缓存。
- 风险分层与预测等级阈值（0.10 / 0.30 / 0.5）是服务层决策规则，随响应 `thresholds` 返回，与模型训练无耦合。

## 八、分析建模结果速览

| 项目 | 结果 |
|---|---|
| 样本量 | 原始 2,137,374 条 → 清洗后 2,136,402 条 |
| 共病率 | 18.10%（386,760 例） |
| 患病率最高 | 抑郁障碍 19.76%、哮喘 14.35%、糖尿病 13.51% |
| 调整后 OR（最强正向） | 现吸烟 2.210、因费用未就医 2.126、肥胖 1.858、缺乏体力活动 1.675、年龄 75+ 2.549 |
| 经济社会梯度 | 收入 ≥5 万 OR=0.337；大学 4 年以上 OR=0.723 |
| 剂量—反应 | 可干预因素 0→3 项，共病率 11.20% → 43.72% |
| 正式模型 | LightGBM @ Set-A（19 维，无标签泄漏） |
| 测试集 AUC（2023） | 0.7740（PR-AUC 0.4595，F1 0.4619） |
| 五折交叉验证 | AUC 0.7815 ± 0.0012 |
| 性能上限参照 | LightGBM @ Set-B（含健康状态后果变量）AUC 0.8202 |

> 关键取舍：Set-B 比 Set-A 高 0.046 AUC，但其所需输入（自评健康、不良天数、行走困难）是疾病的**后果**，
> 干预对象尚未出现症状时拿不到，故正式模型坚持采用 Set-A。详见 docs/建模说明.md。

## 九、文档索引

| 文档 | 内容 |
|---|---|
| docs/部署说明.md | 环境要求、依赖版本、启动步骤、端口、常见问题 |
| docs/接口文档.md | 9 个接口的请求参数、真实响应示例、错误码表 |
| docs/数据字典.md | 37 个字段的中文含义、取值映射、跨年调和表 |
| docs/数据质量报告.md | 清洗前后行数、各规则影响量、缺失率、患病率 |
| docs/分析结论.md | EDA 发现、假设 H1–H3 的检验与判读、检出偏倚说明 |
| docs/建模说明.md | 特征集设计、切分协议、超参、六组模型对比、局限 |
| docs/前端说明.md | 前端技术选型、图表选型论证、交互链路 |
| docs/设计规格.md | 冻结的口径、目录结构、表结构、API 契约 |

## 十、三个必须知道的数据陷阱

1. **主键**：SEQNO 是层内序号（2019 年 41.8 万行仅 1.7 万个不同值），必须以 (year, _STSTR, SEQNO) 组合构造 seq_key。
2. **编码方向**：_RFBING6 是 1=否/2=是，_TOTINDA 是 1=有运动/2=无，与慢病标志位"1=是"相反。本项目统一归一化为 0/1 且 1=状态成立，否则酗酒率会从 13.27% 误报为 86.73%。
3. **标签泄漏**：genhlth / menthlth / physhlth / diffwalk 是疾病后果，不可作为预测特征用于干预场景。

