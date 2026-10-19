# -*- coding: utf-8 -*-
import scrapy


class DatasetItem(scrapy.Item):
    dataset_id = scrapy.Field()
    name = scrapy.Field()
    url = scrapy.Field()
    task = scrapy.Field()
    area = scrapy.Field()
    instances = scrapy.Field()
    features = scrapy.Field()
    characteristics = scrapy.Field()
    feature_type = scrapy.Field()
    has_missing = scrapy.Field()
    crawled_at = scrapy.Field()
    source_page = scrapy.Field()
