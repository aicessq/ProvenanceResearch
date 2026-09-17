# 后端服务镜像。
#
# 设计说明（教学向）
# =================
# 1. 基于 python:3.11-slim，体积小且满足规格 §3.1 的 Python 3.11+ 要求。
# 2. 把依赖安装与代码拷贝分层：先拷贝 pyproject.toml 安装依赖，
#    利用 Docker 层缓存——只要依赖不变，重建镜像时不会重装依赖。
# 3. 运行时工作目录设为 /app/backend，与 docker-compose 中的挂载保持一致。

FROM python:3.11-slim

# 避免 Python 写 .pyc 缓存、并实时刷新日志，便于容器内观察
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# psycopg2-binary 仍需要 libpq 运行库
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend

# 先拷贝依赖描述与源码，再安装。
# 注意：pyproject.toml 中 package-dir 把 "" 映射到 backend/，
# 因此安装时 backend/ 必须已存在于 /app/backend。
COPY pyproject.toml /app/
COPY backend/ /app/backend/
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir /app/.[test]

EXPOSE 8000

# 容器内启动命令：监听 0.0.0.0:8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
