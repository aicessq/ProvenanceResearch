# knowledge_engine 镜像（硬化轮 Compose 的 worker/KE API 共用）。
# 构建上下文=knowledge_engine/。注意：KE 当前依赖含 torch/sentence-transformers
# （历史本地模型能力）；全云迁移完成后按 roadmap 移除本地权重依赖再瘦身镜像。
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml /app/pyproject.toml
COPY backend /app/backend
RUN pip install --no-cache-dir -e .

ENV PYTHONPATH=/app/backend
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
