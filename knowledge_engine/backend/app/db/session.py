"""数据库会话模块（SQLAlchemy 2.x）。

设计说明（教学向）
==================

1. 为什么 Phase 0 就要建数据库会话？
   Phase 0 验收要求“数据库连接正常”。我们需要一个能实际连到 PostgreSQL
   并执行 `SELECT 1` 的引擎，用来做健康检查。同时为后续 Phase（ORM 模型、
   CRUD）预留统一的会话工厂。

2. 为什么用连接池 + sessionmaker？
   - create_engine 默认带连接池，避免每次请求都新建 TCP 连接（建连成本高）；
   - sessionmaker 是一个“会话工厂”，FastAPI 依赖注入时按请求生成一个 Session，
     用完关闭，既隔离又高效。

3. 为什么用同步驱动 psycopg2？
   Phase 0 只做连通性验证，不需要异步带来的复杂度。
   后续 Phase 如需高并发可平滑迁移到 asyncpg + AsyncSession，但那不是 Phase 0 的事。
"""

from __future__ import annotations

import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

logger = logging.getLogger(__name__)

# 读取全局配置
settings = get_settings()

# 创建全局引擎：
# - pool_pre_ping=True：每次借出连接前先发 ping，避免拿到已被服务端断开的死连接；
# - pool_recycle=1800：30 分钟回收连接，防止长时间空闲连接被数据库侧主动关闭。
engine = create_engine(
    settings.postgres_dsn,
    pool_pre_ping=True,
    pool_recycle=1800,
    echo=settings.debug,  # 调试模式下打印 SQL，便于学习观察
)

# 会话工厂：调用 SessionLocal() 即可得到一个 Session
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def check_database_connection() -> bool:
    """检查 PostgreSQL 是否可连接。

    返回:
        True 表示连接正常；False 表示连接失败（异常已记录日志，不向上抛出）。
    """
    try:
        # 用原始连接执行最简单的探活语句
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return True
    except Exception as exc:  # noqa: BLE001 - 健康检查需要吞掉所有连接异常
        logger.error("PostgreSQL 连接检查失败: %s", exc)
        return False
