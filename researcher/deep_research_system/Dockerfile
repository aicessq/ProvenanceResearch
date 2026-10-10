# researcher 后端镜像（硬化轮 Compose）。
# 构建上下文=仓库根（需要顶层 providers/evidence/tools/agent/ingest 契约包）。
FROM python:3.13-slim

WORKDIR /app

COPY researcher/deep_research_system/environment.yml /tmp/environment.yml
RUN pip install --no-cache-dir pyyaml \
    && python -c "import yaml; d=yaml.safe_load(open('/tmp/environment.yml'))['dependencies']; print('\n'.join(next(x['pip'] for x in d if isinstance(x, dict) and 'pip' in x)))" > /tmp/req.txt \
    && pip install --no-cache-dir -r /tmp/req.txt

COPY providers /app/providers
COPY evidence /app/evidence
COPY tools /app/tools
COPY agent /app/agent
COPY ingest /app/ingest
COPY researcher/deep_research_system /app/deep_research_system

WORKDIR /app/deep_research_system
ENV PYTHONPATH=/app
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
