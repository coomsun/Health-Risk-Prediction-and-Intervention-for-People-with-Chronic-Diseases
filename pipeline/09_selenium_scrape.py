# -*- coding: utf-8 -*-
"""09_selenium_scrape.py — Selenium 动态渲染抓取（综合项目加分项）

为什么需要 Selenium：
    UCI 的列表页虽然首屏有 SSR 链接，但分页、筛选与详情页的 Instances/Features
    等元信息由前端 JS 渲染，纯 requests/Scrapy 拿不到。本脚本用无头 Edge 渲染后
    再抽取，作为 Scrapy 的补充。

产出：crawler/output/selenium_datasets.jsonl（原始字段，未加工）

用法：
    python pipeline/09_selenium_scrape.py --keyword health --pages 2
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "crawler", "output", "selenium_datasets.jsonl")


def _local_driver() -> str | None:
    """优先使用仓库内预置的 msedgedriver，避免 Selenium Manager 联网下载失败。"""
    from selenium.webdriver.edge.service import Service  # noqa: F401  (仅用于类型提示)

    cand = os.path.join(ROOT, "crawler", "drivers", "msedgedriver.exe")
    if os.path.exists(cand):
        return cand
    alt = os.path.join(ROOT, "crawler", "drivers", "msedgedriver")
    return alt if os.path.exists(alt) else None


def build_driver(headless: bool = True):
    from selenium import webdriver
    from selenium.webdriver.edge.options import Options
    from selenium.webdriver.edge.service import Service

    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    for a in ("--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage",
              "--window-size=1440,1200", "--log-level=3"):
        opts.add_argument(a)

    exe = _local_driver()
    if exe:
        print("      使用本地驱动:", exe)
        driver = webdriver.Edge(service=Service(executable_path=exe), options=opts)
    else:
        print("      未找到本地驱动，回退到 Selenium Manager")
        driver = webdriver.Edge(options=opts)
    driver.set_page_load_timeout(45)
    return driver


def scrape(keyword: str, pages: int) -> int:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    t0 = time.time()
    print("[1/3] 启动无头 Edge ...")
    driver = build_driver()
    print("      浏览器版本:", driver.capabilities.get("browserVersion"))

    rows, seen = [], set()
    try:
        for page in range(1, pages + 1):
            url = f"https://archive.ics.uci.edu/datasets?search={keyword}&page={page}"
            print("[2/3] 打开第 %d 页: %s" % (page, url))
            driver.get(url)
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "a[href^='/dataset/']"))
            )
            time.sleep(1.5)   # 等 JS 渲染完

            cards = driver.find_elements(By.CSS_SELECTOR, "a[href^='/dataset/']")
            print("      渲染出 %d 个链接" % len(cards))
            for c in cards:
                href = c.get_attribute("href") or ""
                if "/dataset/" not in href:
                    continue
                did = href.rstrip("/").split("/dataset/")[-1].split("/")[0]
                if did in seen:
                    continue
                seen.add(did)
                rows.append({
                    "dataset_id": did,
                    "name": href.rstrip("/").split("/")[-1].replace("+", " "),
                    "url": href,
                    "anchor_text": (c.text or "").strip()[:200],
                    "crawled_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "render_engine": "selenium+edge-headless",
                    "keyword": keyword,
                    "page": page,
                })
            if page < pages:
                time.sleep(1.2)
    finally:
        driver.quit()

    print("[3/3] 写出 %d 条记录" % len(rows))
    with open(OUT, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("      文件:", OUT, "(%.1f KB)" % (os.path.getsize(OUT) / 1024))
    print("DONE 用时 %.1fs" % (time.time() - t0))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keyword", default="health")
    ap.add_argument("--pages", type=int, default=2)
    ap.add_argument("--no-headless", action="store_true")
    args = ap.parse_args()
    try:
        return scrape(args.keyword, args.pages)
    except Exception as e:
        print("SELENIUM FAILED:", type(e).__name__, str(e)[:500])
        return 2


if __name__ == "__main__":
    sys.exit(main())
