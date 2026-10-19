"""慢性病患者健康风险预测与干预 —— RESTful 后端服务包。

模块划分：
    contract  统一响应信封 / 错误码 / 异常处理器 / 耗时中间件
    queries   SQLite 只读聚合查询层（全部统计口径落在 SQL 里）
    main      FastAPI 应用与 9 个契约接口
"""

__version__ = "1.0.0"
