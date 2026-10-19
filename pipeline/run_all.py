# -*- coding: utf-8 -*-
"""run_all.py —— 六环节流水线调度骨架

固定顺序：01 采集 → 02 清洗 → 03 EDA → 04 特征 → 05 训练 → 06 建库
（03/04/05 由其它模块提供，脚本缺失时按“可选步骤”跳过并给出提示）

用法：
  python pipeline/run_all.py                 # 全流程（缺 03/04/05 则跳过）
  python pipeline/run_all.py --only 01,02,06 # 只跑数据工程三件套
  python pipeline/run_all.py --from 02       # 从 02 开始
  python pipeline/run_all.py --strict        # 任何步骤缺失/失败即中断
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPELINE_DIR = os.path.join(ROOT, "pipeline")
PYTHON = os.environ.get("PYSPARK_PYTHON") or sys.executable

# 环境变量（PySpark 必需；在子进程中通过 env 传递）
SPARK_ENV = {
    "JAVA_HOME": os.environ.get("JAVA_HOME", r"D:\jdk17"),
    "SPARK_HOME": os.environ.get("SPARK_HOME", r"D:\sparkhome"),
    "PYSPARK_PYTHON": PYTHON,
    "PYSPARK_DRIVER_PYTHON": PYTHON,
}

# (步骤号, 脚本名, 说明, 是否数据工程模块必需)
STEPS = [
    ("01", "01_download.py", "原始数据采集与 SHA256 校验", True),
    ("02", "02_clean_spark.py", "PySpark 清洗与派生指标", True),
    ("03", "03_eda_spark.py", "PySpark 探索性分析（EDA，其它模块提供）", False),
    ("04", "04_features.py", "特征工程 / 建模数据集（其它模块提供）", False),
    ("05", "05_train.py", "模型训练与评估（其它模块提供）", False),
    ("06", "06_build_db.py", "SQLite 建库与聚合", True),
]


def log(msg: str) -> None:
    print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), msg), flush=True)


def select_steps(args) -> list:
    steps = STEPS
    if args.only:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        steps = [s for s in steps if s[0] in wanted]
    if args.from_step:
        idx = [i for i, s in enumerate(STEPS) if s[0] == args.from_step]
        if not idx:
            raise SystemExit("未知的起始步骤：%s" % args.from_step)
        steps = [s for s in steps if int(s[0]) >= int(STEPS[idx[0]][0])]
    return steps


def run_step(step_id: str, script: str, desc: str, required: bool, strict: bool) -> dict:
    path = os.path.join(PIPELINE_DIR, script)
    if not os.path.exists(path):
        if required:
            log("[%s] 缺少必需脚本 %s" % (step_id, script))
            if strict:
                raise SystemExit(1)
        else:
            log("[%s] 跳过：%s 尚未提供（%s）" % (step_id, script, desc))
        return {"step": step_id, "script": script, "status": "missing", "elapsed_sec": 0}
    log("[%s] 开始：%s —— %s" % (step_id, script, desc))
    t0 = time.time()
    env = dict(os.environ)
    env.update(SPARK_ENV)
    proc = subprocess.run([PYTHON, path], cwd=ROOT, env=env)
    elapsed = round(time.time() - t0, 1)
    status = "ok" if proc.returncode == 0 else "failed(%d)" % proc.returncode
    log("[%s] %s，耗时 %.1f 秒" % (step_id, status, elapsed))
    if proc.returncode != 0 and strict:
        raise SystemExit(proc.returncode)
    return {"step": step_id, "script": script, "status": status, "elapsed_sec": elapsed}


def main() -> int:
    ap = argparse.ArgumentParser(description="六环节流水线调度")
    ap.add_argument("--only", default=None, help="只跑指定步骤，逗号分隔，如 01,02,06")
    ap.add_argument("--from", dest="from_step", default=None, help="从指定步骤开始")
    ap.add_argument("--strict", action="store_true", help="失败或缺失即中断")
    args = ap.parse_args()

    steps = select_steps(args)
    log("待执行步骤：%s" % [s[0] for s in steps])
    t_start = time.time()
    results = [run_step(*s, strict=args.strict) for s in steps]

    total = round(time.time() - t_start, 1)
    log("流水线结束，总耗时 %.1f 秒" % total)
    for r in results:
        log("    %s %-22s %-10s %6.1fs" % (r["step"], r["script"], r["status"], r["elapsed_sec"]))
    failed = [r for r in results if r["status"].startswith("failed")]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
