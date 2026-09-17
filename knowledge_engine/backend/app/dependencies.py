"""依赖注入模块：基础设施客户端与连接检查。

设计说明（教学向）
==================

1. 为什么把 Redis / Qdrant 客户端集中在这里？
   - 规格 §3.2 要求“所有外部模型调用必须统一封装服务层”，
     基础设施客户端也遵循同样思路：统一创建、统一暴露；
   - 集中管理后，FastAPI 路由 / 后续服务层只需 import 即可复用，
     便于在测试中替换为 mock。

2. Phase 0 只做“连通性探活”：
   - Redis：PING
   - Qdrant：获取集群/集合信息（GET /）
   真正的业务调用（写任务状态、写向量等）留给后续 Phase。

3. 为什么连接检查失败要返回 False 而不是抛异常？
   健康检查接口需要能返回“部分不可用”的状态给运维，
   而不是一旦某个组件挂了就让整个 /health/ready 抛 500。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Generator

from redis import Redis
from redis.exceptions import RedisError

from app.config import get_settings
from app.db.session import SessionLocal
from app.workers.celery_app import celery_app

# Qdrant 客户端在 import 阶段尽量延迟创建，避免在未启 Qdrant 时影响启动。
# 这里用懒加载函数获取客户端。
try:
    # qdrant-client 是官方 Python SDK
    from qdrant_client import QdrantClient
    # 不同版本异常类位置不同：优先用 ApiException（该版本基类），
    # 取不到则退回 Exception，保证 import 不会因版本差异失败。
    try:
        from qdrant_client.http.exceptions import ApiException as QdrantApiError
    except ImportError:  # pragma: no cover
        QdrantApiError = Exception  # type: ignore[assignment]
except ImportError:  # pragma: no cover - 仅当依赖未安装时触发
    QdrantClient = None  # type: ignore[assignment]
    QdrantApiError = Exception  # type: ignore[assignment]

logger = logging.getLogger(__name__)
settings = get_settings()


# ---- Redis 客户端 ----
# decode_responses=True：直接返回 str 而不是 bytes，使用更方便
redis_client: Redis = Redis.from_url(settings.redis_url, decode_responses=True)


def check_redis_connection() -> bool:
    """检查 Redis 是否可连接（执行 PING）。"""
    try:
        return bool(redis_client.ping())
    except RedisError as exc:
        logger.error("Redis 连接检查失败: %s", exc)
        return False
    except Exception as exc:  # noqa: BLE001 - 兜底，避免健康检查接口抛 500
        logger.error("Redis 连接检查出现未知异常: %s", exc)
        return False


# ---- Qdrant 客户端（懒加载） ----
_qdrant_client: "QdrantClient | None" = None


def get_qdrant_client() -> "QdrantClient | None":
    """懒加载获取 Qdrant 客户端单例。

    之所以懒加载：Phase 0 在本地跑单元测试时 Qdrant 可能未启动，
    立即创建客户端不会失败（qdrant-client 创建对象不连网），
    但统一用函数获取更便于后续替换与测试 mock。
    """
    global _qdrant_client
    if _qdrant_client is None and QdrantClient is not None:
        _qdrant_client = QdrantClient(url=settings.qdrant_url)
    return _qdrant_client


def check_qdrant_connection() -> bool:
    """检查 Qdrant 是否可连接（调用一次轻量接口）。"""
    client = get_qdrant_client()
    if client is None:
        logger.warning("qdrant-client 未安装，跳过 Qdrant 连接检查")
        return False
    try:
        # get_collections 会真正发起 HTTP 请求，能验证服务可达
        client.get_collections()
        return True
    except QdrantApiError as exc:
        logger.error("Qdrant 连接检查失败: %s", exc)
        return False
    except Exception as exc:  # noqa: BLE001 - 兜底
        logger.error("Qdrant 连接检查出现未知异常: %s", exc)
        return False


REQUIRED_CELERY_TASKS = {
    "app.workers.ingest_worker.ingest_document_task",
    "app.workers.ingest_worker.replace_document_task",
}
_worker_registration_cache: tuple[float, dict[str, list[str]]] | None = None


def check_celery_worker_connection() -> tuple[bool, int, bool]:
    """短超时探活 Worker；较重的任务注册查询使用进程内短期缓存。"""
    global _worker_registration_cache
    inspector = celery_app.control.inspect(timeout=settings.celery_worker_ping_timeout_seconds)
    ping_responses = inspector.ping() or {}
    worker_count = len(ping_responses)
    if worker_count == 0:
        return False, 0, False

    now = time.monotonic()
    if (
        _worker_registration_cache is None
        or now - _worker_registration_cache[0] >= settings.celery_worker_registration_cache_seconds
    ):
        registered_by_worker = inspector.registered() or {}
        _worker_registration_cache = (now, registered_by_worker)
    else:
        registered_by_worker = _worker_registration_cache[1]
    required_tasks_registered = all(
        REQUIRED_CELERY_TASKS.issubset(set(registered_by_worker.get(worker, [])))
        for worker in ping_responses
    )
    return True, worker_count, required_tasks_registered


# ---- FastAPI 数据库会话依赖 ----
def get_db() -> Generator:
    """FastAPI 依赖：按请求提供一个数据库会话，请求结束自动关闭。

    用法（后续 Phase 的路由）：
        @router.get("/")
        def list_items(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
