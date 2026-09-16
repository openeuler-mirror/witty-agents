# NL2sql-Agent Dockerfile
# 构建上下文须为 NL2sql-Agent 源码根目录（含 apps/ nl2sql_core/ configs/ scripts/ fixtures/ requirements.txt）
FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_TRUSTED_HOST=mirrors.aliyun.com

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip3 install --no-cache-dir \
    -r requirements.txt \
    -i https://mirrors.aliyun.com/pypi/simple/

COPY apps/ ./apps/
COPY nl2sql_core/ ./nl2sql_core/
COPY configs/ ./configs/
COPY scripts/ ./scripts/
COPY fixtures/ ./fixtures/

EXPOSE 8199

CMD ["uvicorn", "apps.web.main:app", "--host", "0.0.0.0", "--port", "8199"]
