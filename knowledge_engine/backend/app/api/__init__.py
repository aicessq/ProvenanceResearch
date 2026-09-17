"""API 路由聚合。

设计说明（教学向）
==================

1. 为什么每个业务域一个 router 文件，再在这里聚合？
   - 单一职责：health / upload / query 等各自维护自己的路由；
   - main.py 只需 include 一次聚合 router，启动代码保持干净；
   - 后续 Phase 新增接口时，只需新建对应文件并在本文件中追加一行 include。

2. 当前已聚合：
   - health：健康检查与就绪探针；
   - upload：Phase 2 新文档上传入口；
   - documents：Phase 9 replace / soft delete；
   - eval：Phase 10 评测运行接口；
   - query：Phase 6-8 检索 / rewrite / answer。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api import documents, eval, health, query, upload

api_router = APIRouter()
# 健康检查路由：/health 与 /health/ready 都在 health.router 内
api_router.include_router(health.router)
# Phase 2：启用新文档上传入口
api_router.include_router(upload.router)
# Phase 9：启用文档 replace / soft delete 接口
api_router.include_router(documents.router)
# Phase 10：启用评测运行接口
api_router.include_router(eval.router)
# Phase 6：启用基础检索调试接口
api_router.include_router(query.router)
