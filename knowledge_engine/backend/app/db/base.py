"""SQLAlchemy 声明基类。

设计说明（教学向）
==================

1. 为什么需要 base.py？
   后续 Phase 所有 ORM 模型都要继承同一个 DeclarativeBase，
   这样它们共享同一套元数据（MetaData），Alembic 才能统一管理迁移。
   Phase 0 先把基类放好，Phase 1 加表模型时直接继承即可。

2. Phase 0 不定义任何表模型——避免提前实现 Phase 1 的数据库业务模型。
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """所有 ORM 模型的声明基类。

    后续 Phase 的模型类继承本类，例如：
        class Document(Base): ...
    """
