"""全局配置模块。

设计说明（教学向）
==================

1. 为什么所有配置都从 `.env` 读取？
   规格 §3.2 明确要求“配置来源：全部从 `.env` 读取”。
   把可变参数（数据库地址、端口、密码等）外置到环境变量，
   可以让同一份代码在本地开发 / Docker 容器 / 生产环境无缝切换，
   而不需要改源码，也避免把敏感信息硬编码进仓库。

2. 为什么用 pydantic-settings？
   它是 Pydantic v2 官方推荐的环境变量配置库：
   - 自动从环境变量 / .env 文件加载；
   - 自带类型校验（类型标注写错会在启动时直接报错，而不是运行时才暴露）；
   - 与 FastAPI / Pydantic 生态一致。

3. 配置项会按 Phase 逐步扩展：
   - Phase 0~4：基础设施、上传、持久化、切分；
   - Phase 5：本地 embedding / reranker、Qdrant collection、FTS 参数；
   - Phase 7+：LLM key 与更完整的查询链路配置。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用全局配置。

    所有字段都带默认值，方便在没有 `.env` 的最小环境（如单元测试）下也能实例化。
    生产部署时应通过 `.env` 或真实环境变量覆盖。
    """

    # ---- 通用应用配置 ----
    # 应用名称，仅用于日志/健康检查展示
    app_name: str = Field(default="cybersec-rag-agent", description="应用名称")
    # 调试模式：保留给 SQL 打印、服务调试与测试观测使用
    debug: bool = Field(default=False, description="是否开启调试模式")
    # 允许访问当前 FastAPI 的前端来源，用于本地前后端分离联调
    frontend_allow_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"],
        description="允许跨域访问的前端来源列表",
    )

    # ---- PostgreSQL 配置 ----
    # Docker Compose 内服务名为 postgres，本地开发用 localhost
    postgres_host: str = Field(default="localhost", description="PostgreSQL 主机")
    postgres_port: int = Field(default=5432, description="PostgreSQL 端口")
    postgres_user: str = Field(default="cybersec", description="PostgreSQL 用户名")
    postgres_password: str = Field(default="cybersec", description="PostgreSQL 密码")
    postgres_db: str = Field(default="cybersec_rag", description="PostgreSQL 数据库名")

    # ---- Redis 配置 ----
    redis_host: str = Field(default="localhost", description="Redis 主机")
    redis_port: int = Field(default=6379, description="Redis 端口")
    redis_db: int = Field(default=0, description="Redis 库编号")
    redis_password: str | None = Field(default=None, description="Redis 密码，可为空")

    # ---- Celery Worker 与异步任务恢复配置 ----
    celery_worker_ping_timeout_seconds: float = Field(default=2.0, gt=0)
    celery_worker_registration_cache_seconds: int = Field(default=30, ge=0)
    queued_stale_seconds: int = Field(default=300, gt=0)
    dispatched_queue_stale_seconds: int = Field(default=900, gt=0)
    worker_heartbeat_interval_seconds: int = Field(default=30, gt=0)
    processing_lease_timeout_seconds: int = Field(default=180, gt=0)
    task_recovery_interval_seconds: int = Field(default=60, gt=0)
    task_recovery_batch_size: int = Field(default=50, gt=0)
    task_max_recovery_count: int = Field(default=3, ge=0)
    task_auto_recover_processing: bool = Field(default=False)
    task_status_redis_ttl_seconds: int = Field(default=86400, gt=0)

    # ---- Qdrant 配置 ----
    qdrant_host: str = Field(default="localhost", description="Qdrant 主机")
    qdrant_port: int = Field(default=6333, description="Qdrant HTTP 端口")
    qdrant_collection: str = Field(default="cybersec_chunks", description="Qdrant 集合名")
    qdrant_distance_metric: str = Field(default="Cosine", description="Qdrant 向量距离类型")

    # ---- Phase 2：上传与本地存储配置 ----
    storage_root: Path = Field(default=Path("storage"), description="原始文件存储根目录")
    max_upload_size_mb: int = Field(default=20, description="单文件最大上传大小（MB）")
    allowed_upload_extensions: list[str] = Field(
        default_factory=lambda: [".pdf", ".md", ".markdown", ".txt"],
        description="允许上传的文件扩展名列表",
    )
    allowed_upload_mime_types: list[str] = Field(
        default_factory=lambda: [
            "application/pdf",
            "text/markdown",
            "text/plain",
            "text/x-markdown",
        ],
        description="允许上传的 MIME 类型列表",
    )

    # ---- Phase 5：本地模型与索引配置 ----
    embedding_model_path: Path = Field(default=Path("models/embedding"), description="本地 embedding 模型目录")
    reranker_model_path: Path = Field(default=Path("models/reranker"), description="本地 reranker 模型目录")
    embedding_vector_size: int = Field(default=1024, description="embedding 向量维度")
    embedding_batch_size: int = Field(default=16, description="embedding 批处理大小")
    reranker_batch_size: int = Field(default=16, description="reranker 批处理大小")
    fts_language_config: str = Field(default="simple", description="PostgreSQL FTS 语言配置")

    # ---- Phase 7+：远程 LLM 配置 ----
    llm_api_key: str | None = Field(default=None, description="远程 LLM API key")
    llm_base_url: str | None = Field(default=None, description="远程 LLM base URL")

    @field_validator("allowed_upload_extensions", "allowed_upload_mime_types", mode="before")
    @classmethod
    def parse_csv_list(cls, value: list[str] | str) -> list[str]:
        """支持从 .env 的逗号分隔字符串解析列表配置。"""
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return []

    @field_validator("qdrant_distance_metric")
    @classmethod
    def validate_qdrant_distance_metric(cls, value: str) -> str:
        """限制当前 Phase 支持的 Qdrant 距离类型。"""
        normalized = value.strip()
        if normalized not in {"Cosine", "Dot", "Euclid", "Manhattan"}:
            raise ValueError("qdrant_distance_metric 仅支持 Cosine / Dot / Euclid / Manhattan")
        return normalized

    # Pydantic v2 的配置写法：从 .env 读取，且字段大小写不敏感
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- 派生属性：拼装连接串 ----
    # 为什么用 property 而不是直接写字符串字段？
    # 因为连接串是从“主机/端口/用户名/密码/库名”派生出来的，
    # 用 property 可以保证各子字段一旦变化，连接串自动同步，避免不一致。
    @property
    def postgres_dsn(self) -> str:
        """返回 SQLAlchemy 可用的 PostgreSQL 连接串。"""
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        """返回 redis-py 可用的连接 URL。"""
        if self.redis_password:
            return (
                f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}"
                f"/{self.redis_db}"
            )
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def qdrant_url(self) -> str:
        """返回 Qdrant HTTP 连接 URL。"""
        return f"http://{self.qdrant_host}:{self.qdrant_port}"

    @property
    def celery_broker_url(self) -> str:
        """返回 Celery broker URL。Phase 2 默认复用 Redis。"""
        return self.redis_url

    @property
    def celery_result_backend(self) -> str:
        """返回 Celery result backend URL。Phase 2 默认复用 Redis。"""
        return self.redis_url


@lru_cache
def get_settings() -> Settings:
    """获取全局配置单例。

    用 lru_cache 缓存，避免每次请求都重新解析 .env 文件，
    既提升性能，也保证全进程使用同一份配置。
    """
    return Settings()
