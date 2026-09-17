"""pytest 公共夹具。

设计说明（教学向）
==================

1. 保留 Phase 0 的 `client` 夹具，继续支持不依赖外部基础设施的接口测试。
2. Phase 1 新增数据库相关夹具：
   - `alembic_config`：用于执行迁移；
   - `db_session`：提供真实 PostgreSQL Session；
3. 数据库相关夹具仅服务于带 `integration` 标记的测试；默认 `pytest` 仍不会触发它们。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

# 把 backend 目录加入 sys.path，使得 `import app.main` 在从项目根运行 pytest 时可用
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.session import SessionLocal, engine

ALL_PHASE1_TABLES = [
    "eval_run_items",
    "ingest_tasks",
    "chunks",
    "feedback",
    "eval_runs",
    "eval_dataset_items",
    "document_versions",
    "query_logs",
    "eval_datasets",
    "documents",
]


@pytest.fixture()
def client() -> TestClient:
    """返回 FastAPI 测试客户端。"""
    from app.main import app

    return TestClient(app)


@pytest.fixture(scope="session")
def alembic_config() -> Config:
    """返回项目 Alembic 配置对象。"""
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return config


@pytest.fixture(scope="session")
def migrated_database(alembic_config: Config) -> None:
    """把测试数据库迁移到最新版本。"""
    command.upgrade(alembic_config, "head")


@pytest.fixture()
def db_session(migrated_database: None) -> Session:
    """提供一个真实 PostgreSQL Session，并在测试后清理 Phase 1 相关表。"""
    with engine.begin() as connection:
        connection.execute(text(f'TRUNCATE TABLE {", ".join(ALL_PHASE1_TABLES)} RESTART IDENTITY CASCADE'))

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        with engine.begin() as connection:
            connection.execute(text(f'TRUNCATE TABLE {", ".join(ALL_PHASE1_TABLES)} RESTART IDENTITY CASCADE'))
