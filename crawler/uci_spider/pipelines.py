# -*- coding: utf-8 -*-
"""去重 + 写 JSONL。保留原始抓取字段，不做任何统计或格式化加工。"""
import json
import os
from datetime import datetime, timezone


class JsonLinesPipeline:
    def __init__(self):
        self.seen = set()
        self.out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "uci_spider", "output", "uci_datasets.jsonl")
        os.makedirs(os.path.dirname(self.out), exist_ok=True)
        self.fh = open(self.out, "w", encoding="utf-8")

    def process_item(self, item, spider):
        key = item.get("dataset_id")
        if key in self.seen:
            return item
        self.seen.add(key)
        row = {k: (v if not isinstance(v, datetime) else v.isoformat()) for k, v in item.items()}
        self.fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.fh.flush()
        return item

    def close_spider(self, spider):
        self.fh.close()
        spider.logger.info("已写出 %d 条记录 -> %s", len(self.seen), self.out)
