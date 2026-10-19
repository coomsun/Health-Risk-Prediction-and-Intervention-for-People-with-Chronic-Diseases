# -*- coding: utf-8 -*-
"""uci_datasets.py — 抓取 UCI 机器学习仓库的数据集目录

目标：https://archive.ics.uci.edu/datasets?search=<关键词>
产出：uci_spider/output/uci_datasets.jsonl（原始字段，未加工）

说明：UCI 列表页为服务端渲染，链接形如 /dataset/45/heart+disease，
      详情页含 Instances/Features/Task 等元信息，逐条跟进抓取。
"""
import re
from datetime import datetime, timezone

import scrapy

from uci_spider.items import DatasetItem  # noqa: E402


class UciDatasetsSpider(scrapy.Spider):
    name = "uci_datasets"
    allowed_domains = ["archive.ics.uci.edu"]

    custom_settings = {
        "DOWNLOAD_DELAY": 1.2,
        "CLOSESPIDER_TIMEOUT": 300,      # 最多跑 5 分钟，避免作业时长时间占用
        "CLOSESPIDER_PAGECOUNT": 200,
    }

    def __init__(self, keyword="health", max_pages=3, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.keyword = keyword
        self.max_pages = int(max_pages)

    async def start(self):
        """Scrapy 2.13+ 的新入口：异步生成器。

        旧版 start_requests() 在 2.19 已被移除，若仍定义该方法会被静默忽略，
        表现为「spider 打开后零请求、零产出」。
        """
        for page in range(1, self.max_pages + 1):
            url = ("https://archive.ics.uci.edu/datasets"
                   f"?search={self.keyword}&page={page}")
            yield scrapy.Request(url, callback=self.parse_list,
                                 meta={"page": page}, dont_filter=True)

    def parse_list(self, response):
        links = response.css("a[href^='/dataset/']::attr(href)").getall()
        seen = set()
        for href in links:
            if href in seen:
                continue
            seen.add(href)
            yield response.follow(href, callback=self.parse_detail,
                                  meta={"source_page": response.url})

    def parse_detail(self, response):
        m = re.search(r"/dataset/(\d+)/([^/?#]+)", response.url)
        if not m:
            return
        did, slug = m.group(1), m.group(2)

        # UCI 详情页的元信息结构为：<div><h1>标签</h1><p>值</p></div>
        # 例如 <h1># Instances</h1><p>583</p>、<h1>Subject Area</h1><p>Health and Medicine</p>
        # 因此按「h1 文本匹配 → 取同级下一个 p」来抽取。
        def meta_of(label: str):
            for h1 in response.css("h1"):
                text = (h1.css("::text").get() or "").strip()
                if label.lower() in text.lower():
                    sib = h1.xpath("following-sibling::p[1]")
                    if sib:
                        return (sib[0].css("::text").get() or "").strip()
            return None

        def clean_num(v):
            """Instances/Features 只保留数字，去掉千分位与多余字符。"""
            if not v:
                return None
            m = re.search(r"[d,]+", v)
            return m.group(0).replace(",", "") if m else v

        yield DatasetItem(
            dataset_id=did,
            name=slug.replace("+", " "),
            url=response.url,
            task=meta_of("Associated Tasks"),
            area=meta_of("Subject Area"),
            instances=clean_num(meta_of("# Instances")),
            features=clean_num(meta_of("# Features")),
            characteristics=meta_of("Dataset Characteristics"),
            feature_type=meta_of("Feature Type"),
            has_missing=meta_of("Has Missing Values?"),
            crawled_at=datetime.now(timezone.utc).isoformat(),
            source_page=response.meta.get("source_page"),
        )
