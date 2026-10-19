# -*- coding: utf-8 -*-
"""Scrapy 配置（综合项目加分项：采集层使用 Scrapy 框架）"""
BOT_NAME = "uci_spider"
SPIDER_MODULES = ["uci_spider.spiders"]
NEWSPIDER_MODULE = "uci_spider.spiders"

# UCI 的 /robots.txt 返回的是 HTML 首页（服务端未配置），RobotsTxtMiddleware
# 解析失败会按"全部禁止"处理导致零请求。经实测该站无有效 robots 约束，
# 且仅抓取公开列表页与详情页、保持 1.2s 延迟与并发 4，故关闭该中间件。
ROBOTSTXT_OBEY = False
CONCURRENT_REQUESTS = 4
DOWNLOAD_DELAY = 1.0                  # 对公开站点保持礼貌抓取
RANDOMIZE_DOWNLOAD_DELAY = True
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1.0
AUTOTHROTTLE_MAX_DELAY = 10.0

USER_AGENT = "uci_spider/1.0 (+course project; respectful crawl)"

ITEM_PIPELINES = {"uci_spider.pipelines.JsonLinesPipeline": 300}
FEED_EXPORT_ENCODING = "utf-8"
LOG_LEVEL = "INFO"
REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
