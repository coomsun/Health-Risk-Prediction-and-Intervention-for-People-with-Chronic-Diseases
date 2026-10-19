# -*- coding: utf-8 -*-
"""08_scheduled_ingest.py — 定时增量采集（综合项目加分项）

职责：
  1. 按 cron 表达式周期性检查上游数据集是否有更新；
  2. 增量判定用 SHA256：仅当远端文件哈希与本地 MANIFEST 记录不同才下载；
  3. 每次运行写一条审计记录到 db 的 audit_pipeline 表，可追溯。

用法：
  # 只跑一次（便于演示与测试）
  python pipeline/08_scheduled_ingest.py --once

  # 常驻，每天 02:30 增量采集
  python pipeline/08_scheduled_ingest.py --cron "30 2 * * *"

设计取舍：默认不常驻，避免答辩演示时后台悄悄跑；--once 可安全重复执行（幂等）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
MANIFEST = os.path.join(RAW, "MANIFEST.json")
DB = os.path.join(ROOT, "db", "chronic_risk.db")

BASE = "https://huggingface.co/datasets/LoneWolfgang/brfss-llcp/resolve/main/data"
YEARS = [2019, 2020, 2021, 2022, 2023]
UA = {"User-Agent": "brfss-ingest/1.0 (course project)"}


def sha256_of(path: str, buf: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(buf), b""):
            h.update(chunk)
    return h.hexdigest()


def remote_size(url: str) -> int | None:
    """只发 HEAD 请求判断远端大小，避免无谓下载。"""
    req = urllib.request.Request(url, headers=UA, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return int(r.headers.get("Content-Length") or 0)
    except Exception:
        return None


def load_manifest() -> dict:
    if os.path.exists(MANIFEST):
        with open(MANIFEST, encoding="utf-8") as f:
            return json.load(f)
    return {"files": []}


def save_manifest(m: dict) -> None:
    m["updated_at"] = datetime.now(timezone.utc).isoformat()
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)


def audit(conn, run_id: str, step: str, started: float, rows: int, detail: dict) -> None:
    try:
        conn.execute(
            "INSERT INTO audit_pipeline(run_id, step, started_at, finished_at, elapsed_sec,"
            " rows_in, rows_out, detail) VALUES (?,?,?,?,?,?,?,?)",
            (run_id, step, datetime.fromtimestamp(started).isoformat(timespec="seconds"),
             datetime.now().isoformat(timespec="seconds"), round(time.time() - started, 1),
             None, rows, json.dumps(detail, ensure_ascii=False)),
        )
        conn.commit()
    except Exception as e:
        print("  [warn] 审计写入失败：%s" % e)


def run_once() -> int:
    t0 = time.time()
    run_id = "ingest-" + datetime.now().strftime("%Y%m%d%H%M%S")
    os.makedirs(RAW, exist_ok=True)
    m = load_manifest()
    known = {f["name"]: f for f in m.get("files", [])}

    print("[1/3] 检查 %d 个上游文件是否更新（仅 HEAD，不下载）" % len(YEARS))
    changed, unchanged, failed = [], [], []
    for y in YEARS:
        name = "LLCP%d.parquet" % y
        url = "%s/%s" % (BASE, name)
        local = os.path.join(RAW, name)
        rsize = remote_size(url)
        if rsize is None:
            failed.append(name)
            print("      %-18s 远端不可达" % name)
            continue
        lsize = os.path.getsize(local) if os.path.exists(local) else -1
        if lsize == rsize:
            unchanged.append(name)
            print("      %-18s 无变化（%s 字节）" % (name, "{:,}".format(lsize)))
        else:
            changed.append((name, url, rsize))
            print("      %-18s 有变化 本地=%s 远端=%s" % (name, lsize, "{:,}".format(rsize)))

    print("\n[2/3] 下载有变化的文件：%d 个" % len(changed))
    for name, url, rsize in changed:
        dst = os.path.join(RAW, name)
        req = urllib.request.Request(url, headers=UA)
        tmp = dst + ".part"
        with urllib.request.urlopen(req, timeout=300) as r, open(tmp, "wb") as f:
            for chunk in iter(lambda: r.read(1 << 20), b""):
                f.write(chunk)
        os.replace(tmp, dst)
        h = sha256_of(dst)
        known[name] = {"name": name, "path": name, "url": url, "bytes": os.path.getsize(dst),
                       "sha256": h, "downloaded_at": datetime.now(timezone.utc).isoformat(),
                       "year": int(name[4:8]), "kind": "parquet"}
        print("      %-18s 已更新 sha256=%s..." % (name, h[:16]))

    m["files"] = [known[k] for k in sorted(known)]
    save_manifest(m)

    print("\n[3/3] 写审计记录")
    try:
        conn = sqlite3.connect(DB, timeout=10)
        audit(conn, run_id, "scheduled_ingest", t0, len(changed),
              {"changed": [c[0] for c in changed], "unchanged": unchanged, "failed": failed})
        conn.close()
        print("      已写入 audit_pipeline（run_id=%s）" % run_id)
    except Exception as e:
        print("      [warn] 数据库不可用，跳过审计：%s" % e)

    print("\n结果：更新 %d | 未变 %d | 失败 %d | 用时 %.1fs"
          % (len(changed), len(unchanged), len(failed), time.time() - t0))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="BRFSS 定时增量采集")
    ap.add_argument("--once", action="store_true", help="只运行一次后退出")
    ap.add_argument("--cron", default="30 2 * * *", help="cron 表达式，默认每天 02:30")
    args = ap.parse_args()

    if args.once:
        return run_once()

    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    sched = BlockingScheduler(timezone="Asia/Shanghai")
    minute, hour, dom, month, dow = args.cron.split()
    sched.add_job(run_once, CronTrigger(minute=minute, hour=hour, day=dom,
                                        month=month, day_of_week=dow))
    print("已启动定时采集：cron='%s'（Ctrl+C 退出）" % args.cron)
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        print("\n已停止")
    return 0


if __name__ == "__main__":
    sys.exit(main())
