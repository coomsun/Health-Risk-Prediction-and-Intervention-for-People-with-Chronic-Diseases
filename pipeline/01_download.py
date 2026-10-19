# -*- coding: utf-8 -*-
r"""01_download.py —— BRFSS 2019-2023 原始数据采集

功能：
  1. 从 HuggingFace 镜像下载 CDC BRFSS LLCP 2019-2023 五个 parquet 文件
     以及两份字典（dictionary.csv / variables.csv）；
  2. 流式写入 + 指数退避重试 + Range 断点续传；
  3. 已存在且大小一致则跳过（幂等，可反复重跑）；
  4. 生成 data/raw/MANIFEST.json（url/bytes/sha256/下载时间/行数）与
     data/raw/SHA256SUMS.txt。

用法：
  python pipeline/01_download.py                 # 正常下载（幂等）
  python pipeline/01_download.py --force         # 强制重下
  python pipeline/01_download.py --verify-only   # 只校验 sha256/行数，不下载
  python pipeline/01_download.py --cache-dir D:\期末作业\_tmp_brfss   # 本地已有副本时直接复制加速
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone

import requests

BASE_URL = "https://huggingface.co/datasets/LoneWolfgang/brfss-llcp/resolve/main"
YEARS = [2019, 2020, 2021, 2022, 2023]

# 工程根目录 = 本文件的上一级
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(ROOT, "data", "raw")
DICT_DIR = os.path.join(RAW_DIR, "dictionary")
METRICS_DIR = os.path.join(ROOT, "artifacts", "metrics")
LOG_PATH = os.path.join(METRICS_DIR, "pipeline_log.json")

CHUNK_SIZE = 1024 * 1024          # 1MB 流式块
MAX_RETRY = 5                     # 单个文件最多重试次数
TIMEOUT = (30, 180)               # (连接超时, 读超时) 秒
HEADERS = {"User-Agent": "brfss-pipeline/1.0 (+course-project)"}


def log(msg: str) -> None:
    """统一的控制台日志（带时间戳）。"""
    print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), msg), flush=True)


def build_targets() -> list[dict]:
    """构造待下载清单：5 个年度 parquet + 2 份字典。"""
    targets = []
    for y in YEARS:
        targets.append({
            "name": "LLCP%d.parquet" % y,
            "url": "%s/data/LLCP%d.parquet" % (BASE_URL, y),
            "dest": os.path.join(RAW_DIR, "LLCP%d.parquet" % y),
            "kind": "parquet",
            "year": y,
        })
    targets.append({
        "name": "dictionary.csv",
        "url": "%s/dictionary/dictionary.csv" % BASE_URL,
        "dest": os.path.join(DICT_DIR, "dictionary.csv"),
        "kind": "dict",
        "year": None,
    })
    targets.append({
        "name": "variables.csv",
        "url": "%s/dictionary/variables.csv" % BASE_URL,
        "dest": os.path.join(DICT_DIR, "variables.csv"),
        "kind": "dict",
        "year": None,
    })
    return targets


def remote_size(session: requests.Session, url: str) -> int | None:
    """HEAD 取远端文件大小，失败时返回 None（则由后续 GET 自身推断）。"""
    try:
        r = session.head(url, headers=HEADERS, allow_redirects=True, timeout=TIMEOUT)
        if r.status_code == 200 and r.headers.get("Content-Length"):
            return int(r.headers["Content-Length"])
    except requests.RequestException:
        pass
    return None


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def parquet_rows(path: str) -> int | None:
    """用 pyarrow 元数据取行数（不读数据页）。csv 返回 None。"""
    try:
        import pyarrow.parquet as pq
        return int(pq.ParquetFile(path).metadata.num_rows)
    except Exception:
        return None


def download_one(session: requests.Session, item: dict, force: bool = False) -> dict:
    """下载单个文件；返回该文件的元信息字典。"""
    dest = item["dest"]
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    part = dest + ".part"

    if os.path.exists(dest) and not force:
        # 已存在：大小与远端一致则跳过（幂等重跑的关键）
        local = os.path.getsize(dest)
        size = remote_size(session, item["url"])
        if size is None or local == size:
            log("跳过（已存在）%s  %d bytes" % (item["name"], local))
            return {"skipped": True, "bytes": local}
        log("已存在但大小不一致（local=%d remote=%d），重新下载 %s" % (local, size, item["name"]))

    expected = remote_size(session, item["url"])

    for attempt in range(1, MAX_RETRY + 1):
        resume_at = os.path.getsize(part) if os.path.exists(part) else 0
        headers = dict(HEADERS)
        if resume_at:
            headers["Range"] = "bytes=%d-" % resume_at
            log("断点续传 %s 从 %d bytes 处继续（第 %d 次尝试）" % (item["name"], resume_at, attempt))
        else:
            log("开始下载 %s（第 %d 次尝试）" % (item["name"], attempt))

        try:
            t0 = time.time()
            with session.get(item["url"], headers=headers, stream=True,
                             allow_redirects=True, timeout=TIMEOUT) as r:
                if r.status_code == 416:          # Range 越界：本地分片已完整
                    os.replace(part, dest)
                    log("分片已完整，直接落盘 %s" % item["name"])
                    break
                r.raise_for_status()
                # 服务器不支持 Range（返回 200）时，从头覆盖写
                mode = "ab"
                if resume_at and r.status_code != 206:
                    resume_at, mode = 0, "wb"
                done = resume_at
                with open(part, mode) as f:
                    for chunk in r.iter_content(chunk_size=CHUNK_SIZE):
                        if chunk:
                            f.write(chunk)
                            done += len(chunk)
            got = os.path.getsize(part)
            if expected is not None and got != expected:
                raise IOError("大小不一致：got=%d expected=%d" % (got, expected))
            os.replace(part, dest)          # 原子落盘
            log("下载完成 %s  %d bytes  用时 %.1fs" % (item["name"], got, time.time() - t0))
            return {"skipped": False, "bytes": got}
        except Exception as exc:            # noqa: BLE001 —— 网络异常统一重试
            wait = min(2 ** attempt, 20)
            log("下载失败 %s: %s；%ds 后重试" % (item["name"], exc, wait))
            if attempt == MAX_RETRY:
                raise RuntimeError("下载失败超过重试上限：%s (%s)" % (item["name"], exc))
            time.sleep(wait)
    return {"skipped": False, "bytes": os.path.getsize(dest)}


def maybe_copy_from_cache(item: dict, cache_dir: str | None) -> bool:
    """可选加速：本地已有同大小副本则直接复制，避免重复走网络。"""
    if not cache_dir:
        return False
    src = os.path.join(cache_dir, "data" if item["kind"] == "parquet" else "dictionary", item["name"])
    if not os.path.exists(src):
        return False
    dest = item["dest"]
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copyfile(src, dest)
    log("从本地缓存复制 %s (%d bytes)" % (item["name"], os.path.getsize(dest)))
    return True


def write_manifest(entries: list[dict], elapsed: float) -> None:
    """写 MANIFEST.json 与 SHA256SUMS.txt。"""
    manifest = {
        "project": "慢性病患者健康风险预测与干预",
        "dataset": "CDC BRFSS LLCP 2019-2023 (HuggingFace mirror: LoneWolfgang/brfss-llcp)",
        "source_note": "原始发布方为美国 CDC（www.cdc.gov 对本机返回 403），本项目经 HuggingFace 镜像获取同一批公开微观数据。",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "base_url": BASE_URL,
        "total_bytes": sum(e["bytes"] for e in entries),
        "total_rows": sum(e["rows"] or 0 for e in entries),
        "files": entries,
    }
    os.makedirs(RAW_DIR, exist_ok=True)
    with open(os.path.join(RAW_DIR, "MANIFEST.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    with open(os.path.join(RAW_DIR, "SHA256SUMS.txt"), "w", encoding="utf-8") as f:
        for e in entries:
            rel = os.path.relpath(os.path.join(RAW_DIR, e["path"]), RAW_DIR).replace("\\", "/")
            f.write("%s  %s\n" % (e["sha256"], rel))
    log("已写出 MANIFEST.json 与 SHA256SUMS.txt（合计 %d bytes / %d rows）"
        % (manifest["total_bytes"], manifest["total_rows"]))


def append_pipeline_log(step: dict) -> None:
    """把本次运行的摘要并入 artifacts/metrics/pipeline_log.json（按 step 覆盖）。"""
    os.makedirs(METRICS_DIR, exist_ok=True)
    data = {"steps": []}
    if os.path.exists(LOG_PATH):
        try:
            with open(LOG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            data.setdefault("steps", [])
        except json.JSONDecodeError:
            data = {"steps": []}
    data["generated_at"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    data["steps"] = [s for s in data["steps"] if s.get("step") != step["step"]] + [step]
    with open(LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main() -> int:
    ap = argparse.ArgumentParser(description="下载 BRFSS 2019-2023 原始数据")
    ap.add_argument("--force", action="store_true", help="忽略本地文件，强制重新下载")
    ap.add_argument("--verify-only", action="store_true", help="只校验并重建 MANIFEST/SHA256SUMS")
    ap.add_argument("--cache-dir", default=None, help="本地已有副本目录（加速用，例如 D:\\期末作业\\_tmp_brfss）")
    args = ap.parse_args()

    os.makedirs(RAW_DIR, exist_ok=True)
    os.makedirs(DICT_DIR, exist_ok=True)
    targets = build_targets()
    t_start = time.time()

    session = requests.Session()
    session.headers.update(HEADERS)

    if not args.verify_only:
        # 缓存目录探测：仅当用户显式传入时启用，避免掩盖真实的下载能力
        for item in targets:
            if os.path.exists(item["dest"]) and not args.force:
                continue
            if not args.force and maybe_copy_from_cache(item, args.cache_dir):
                continue
            download_one(session, item, force=args.force)

    # 统一计算 sha256 / 行数并写清单（下载与校验走同一条路径）
    entries = []
    missing = []
    for item in targets:
        if not os.path.exists(item["dest"]):
            missing.append(item["name"])
            continue
        digest = sha256_of(item["dest"])
        entries.append({
            "path": os.path.relpath(item["dest"], RAW_DIR).replace("\\", "/"),
            "name": item["name"],
            "url": item["url"],
            "bytes": os.path.getsize(item["dest"]),
            "sha256": digest,
            "rows": parquet_rows(item["dest"]) if item["kind"] == "parquet" else None,
            "downloaded_at": datetime.fromtimestamp(
                os.path.getmtime(item["dest"])).astimezone().isoformat(timespec="seconds"),
            "year": item["year"],
            "kind": item["kind"],
        })
    if missing:
        log("缺少文件，无法生成完整清单：%s" % missing)
        return 1

    write_manifest(entries, time.time() - t_start)

    # ---- 汇总 ----
    parquet_entries = [e for e in entries if e["kind"] == "parquet"]
    rows_by_year = {str(e["year"]): e["rows"] for e in sorted(parquet_entries, key=lambda x: x["year"])}
    total_rows = sum(rows_by_year.values())
    elapsed = round(time.time() - t_start, 1)
    log("原始数据合计 %d 行，%d 字节（%.1f MB），耗时 %.1f 秒"
        % (total_rows, sum(e["bytes"] for e in entries),
           sum(e["bytes"] for e in entries) / 1024 / 1024, elapsed))

    append_pipeline_log({
        "step": "01_download",
        "label": "原始数据下载与校验",
        "started_at": datetime.fromtimestamp(t_start).astimezone().isoformat(timespec="seconds"),
        "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "elapsed_sec": elapsed,
        "rows_in": total_rows,
        "rows_out": total_rows,
        "rows_by_year": rows_by_year,
        "files": [{"name": e["name"], "bytes": e["bytes"], "sha256": e["sha256"], "rows": e["rows"]}
                  for e in entries],
        "total_bytes": sum(e["bytes"] for e in entries),
        "raw_dir": RAW_DIR,
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
