# 慢性病患者健康风险预测与干预 —— 运行镜像
# 说明：数据与模型体积较大（db 361MB、模型 3MB），不打进镜像，
#       通过 volume 挂载，符合"数据与代码分离"的工程惯例。
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 仅安装服务层所需依赖（不含 pyspark/torch 等重型训练依赖，
# 训练在宿主机完成后再挂载产物，镜像更小、启动更快）
COPY requirements-api.txt /app/requirements-api.txt
RUN pip install --no-cache-dir -r /app/requirements-api.txt

COPY api/ /app/api/
COPY web/ /app/web/
COPY db/schema.sql /app/db/schema.sql

# 运行期通过 volume 挂载数据库与模型
RUN mkdir -p /app/db /app/artifacts/model /app/artifacts/metrics

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4).status==200 else 1)"

CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
