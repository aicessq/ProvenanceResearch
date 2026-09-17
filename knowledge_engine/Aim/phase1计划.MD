# Phase 1 实施计划（数据库模型与迁移）

> 本计划基于当前仓库 **Phase 0 已完成** 的现状编写，目标是在不越过规格边界的前提下，推进到 **Phase 1：数据库模型与迁移**。
> 
> 权威依据：
> - `Doc/文档2.MD`
> - 当前仓库 README（Phase 0 实现说明）
> - 当前代码骨架与测试结构

---

## 一、Phase 1 的目标

根据权威规格，Phase 1 的唯一目标是：

**完成核心数据库表、SQLAlchemy 模型、Alembic 迁移以及最小基础 CRUD 能力。**

这一阶段的重点不是业务流程，不是上传，不是解析，也不是检索，而是把后续所有功能依赖的持久化地基先搭好。

---

## 二、必须严格遵守的范围边界

### 2.1 Phase 1 本次必须实现

按照规格，Phase 1 必须完成以下内容：

1. 实现 `documents` 模型
2. 实现 `document_versions` 模型
3. 实现 `chunks` 模型
4. 实现 `query_logs` 模型
5. 实现 `feedback` 模型
6. 实现 `ingest_tasks` 模型
7. 实现 `eval_datasets / eval_dataset_items / eval_runs / eval_run_items` 模型
8. 配置 Alembic
9. 生成首个 migration
10. 添加基础 CRUD

### 2.2 Phase 1 明确不能提前做的内容

本阶段不要提前实现以下内容：

- 不要实现 `/documents/upload`
- 不要实现文件保存
- 不要实现 `file_hash` 计算流程
- 不要实现 Celery 入库任务逻辑
- 不要实现 parser / cleaner / chunk service 真实业务逻辑
- 不要实现 embedding / reranker / Qdrant 写入
- 不要实现 PostgreSQL FTS 检索逻辑
- 不要实现 query pipeline
- 不要实现 replace / chunk diff 更新逻辑

如果某些后续接口或服务在当前阶段需要引用，只允许保留最小占位，不允许补全业务实现。

---

## 三、当前仓库现状评估

当前仓库已经完成了 Phase 0，具备以下基础：

- FastAPI 应用骨架已可运行
- `docker-compose.yml` 已接通 PostgreSQL / Redis / Qdrant / backend
- `app/config.py` 已具备配置中心能力
- `app/db/session.py` 已具备数据库引擎与连接检查能力
- `app/dependencies.py` 已具备共享依赖与基础设施联通检查
- `README.md` 已作为 Phase 0 中文实现说明
- `backend/tests/` 已有健康检查、配置与集成测试结构

这意味着 Phase 1 不需要再解决“工程能否启动”，而是可以直接落到数据库层实现。

---

## 四、Phase 1 的实施原则

### 4.1 先冻结模型，再生成迁移

不要先写 migration 再回头补 ORM 模型。正确顺序应是：

1. 先明确表结构
2. 再写 SQLAlchemy 模型
3. 再配置 Alembic
4. 再生成 migration
5. 再跑升级验证

### 4.2 以权威规格中的表结构为准

所有表字段、索引、约束、JSONB 默认值、状态字段、主外键关系，都必须以 `Doc/文档2.MD` 中已完善的数据库设计为准。

### 4.3 路由层仍然保持极薄

Phase 1 即使要补基础 CRUD，也应遵循既有分层：

- API 层只做输入输出组织
- 数据库访问逻辑放在 model / db / service 辅助层中
- 不要把建表、事务、查询逻辑散落在 route 中

### 4.4 测试先覆盖“模型正确性”和“迁移可用性”

这一阶段最重要的不是 HTTP 接口数量，而是：

- ORM 映射是否正确
- migration 是否能成功升级
- 表是否真的建出来
- 基础插入查询是否可用

---

## 五、建议的实现拆分

建议把 Phase 1 拆成 6 个小步骤执行。

---

## 六、Step 1：整理数据库基础层

### 目标

让当前数据库基础层从“只有连接检查”升级到“支持模型注册与迁移”。

### 建议任务

1. 检查 `backend/app/db/base.py`
   - 确认 Declarative Base 定义清晰
   - 若尚未统一 metadata，可在这里集中管理

2. 检查 `backend/app/db/session.py`
   - 保持现有 engine / session 工厂能力
   - 为后续 Alembic 使用统一数据库 URL 提供支持

3. 检查 `backend/app/models/__init__.py`
   - 让后续模型可在此集中导入，便于 Alembic 自动发现 metadata

### 产出

- 可供 Alembic 引用的统一 Base
- 明确的 models 导入入口

---

## 七、Step 2：实现核心 ORM 模型

### 目标

按规格落地全部核心表。

### 必须实现的模型文件

建议至少包含：

- `backend/app/models/document.py`
- `backend/app/models/document_version.py`
- `backend/app/models/chunk.py`
- `backend/app/models/query_log.py`
- `backend/app/models/feedback.py`
- `backend/app/models/ingest_task.py`
- `backend/app/models/eval_dataset.py`
- `backend/app/models/eval_dataset_item.py`
- `backend/app/models/eval_run.py`
- `backend/app/models/eval_run_item.py`

### 模型实现要求

1. 主键统一 UUID
2. 时间字段统一使用数据库默认时间
3. JSONB 字段必须带默认值
4. 所有外键显式声明
5. 关系字段 `relationship()` 要适度补齐，便于后续 Phase 使用
6. 不要提前把后续业务行为硬编码进模型方法中

### 特别注意

#### documents

- `current_version_id` 允许为空
- `status` 默认 `active`
- `security_domain` / `tags` 为 JSONB 数组默认值

#### document_versions

- `document_id + version_no` 必须唯一
- `file_hash`、`file_size`、`mime_type`、`storage_path` 必须保留
- `version_status` 默认 `active`

#### chunks

- 必须包含 `parent_chunk_id`
- 必须包含 `normalized_text`
- 必须包含 `chunk_hash`
- 必须包含 `search_tsv`
- `is_active` 默认 `true`

#### ingest_tasks

- 明确保留 `task_type`、`status`、`progress`、`finished_at`

#### 评测相关表

- 四张表都要补齐，不要遗漏
- 这是当前规格中已经提前约定好的内容

---

## 八、Step 3：配置 Alembic

### 目标

让仓库正式具备 schema migration 能力。

### 建议任务

1. 完善 `backend/alembic.ini`
2. 创建 `backend/alembic/` 所需目录与脚本模板
3. 配置 `env.py` 读取项目的 SQLAlchemy metadata
4. 确保 Alembic 使用当前项目配置中的数据库地址

### 关键要求

- 不要手写与模型不一致的 migration
- migration 配置要能在当前项目结构下稳定运行
- 优先保证 `alembic upgrade head` 可执行

---

## 九、Step 4：生成首个 migration

### 目标

生成并验证第一版数据库结构。

### 建议任务

1. 生成首个 migration
2. 检查生成结果是否包含：
   - 所有核心表
   - 必要唯一约束
   - 必要索引
   - 外键关系
3. 如 autogenerate 漏掉 GIN / 特殊索引，则人工修正 migration

### 必查项

首个 migration 必须覆盖：

- `documents`
- `document_versions`
- `chunks`
- `query_logs`
- `feedback`
- `ingest_tasks`
- `eval_datasets`
- `eval_dataset_items`
- `eval_runs`
- `eval_run_items`

并检查是否包含：

- `idx_documents_*`
- `idx_document_versions_*`
- `idx_chunks_*`
- `idx_query_logs_*`
- `idx_feedback_*`
- `idx_ingest_tasks_*`
- `idx_eval_*`

---

## 十、Step 5：补基础 CRUD 能力

### 目标

满足规格中“添加基础 CRUD”的最低要求，但不越过 Phase 边界。

### 建议范围

基础 CRUD 不需要做成完整业务 API，可先做成：

- 最小 repository / data access 辅助函数
- 或最小 service 级创建查询函数
- 必要时再暴露少量内部测试使用接口

### 推荐优先实现的能力

1. 创建 document
2. 创建 document_version
3. 创建 chunk
4. 创建 ingest_task
5. 创建 eval_dataset
6. 创建 eval_run
7. 根据主键查询对象

### 不建议此时扩展的内容

- 分页列表接口
- 复杂筛选 API
- 上传触发型 CRUD
- 任何 query pipeline 相关逻辑

---

## 十一、Step 6：测试与验收

### 目标

确保 Phase 1 的成果可运行、可升级、可插入、可查询。

### 至少要补的测试

#### 1. 模型层测试

建议新增：

- `backend/tests/test_models.py`
- `backend/tests/test_crud.py`

可覆盖：

- model 默认值是否正确
- JSONB 默认值是否正确
- 唯一约束是否生效
- 外键关系是否生效

#### 2. migration 测试

至少验证：

- `alembic upgrade head` 成功
- 所有核心表已创建
- 关键索引存在

#### 3. 数据库集成测试

至少验证：

- 可以插入 `document`
- 可以插入 `document_version`
- 可以插入 `chunk`
- 可以插入 `ingest_task`
- 可以插入 `eval_dataset` 和 `eval_run`

### 验收命令建议

```bash
# 1. 启动基础设施
docker compose up -d postgres redis qdrant

# 2. 进入 backend 目录
cd backend

# 3. 执行迁移
alembic upgrade head

# 4. 跑单元测试
pytest

# 5. 跑数据库相关测试
pytest backend/tests/test_models.py backend/tests/test_crud.py
```

### Phase 1 必须达到的验收结果

- `alembic upgrade head` 成功
- 可以创建 `document`
- 可以创建 `version`
- 可以创建 `chunk`
- 可以创建 `ingest_task`
- 可以创建 `eval dataset / eval run`
- 单元测试通过

---

## 十二、推荐文件改动清单

以下是执行 Phase 1 时大概率会涉及的文件：

### 需要新增或完善的文件

- `backend/app/models/document.py`
- `backend/app/models/document_version.py`
- `backend/app/models/chunk.py`
- `backend/app/models/query_log.py`
- `backend/app/models/feedback.py`
- `backend/app/models/ingest_task.py`
- `backend/app/models/eval_dataset.py`
- `backend/app/models/eval_dataset_item.py`
- `backend/app/models/eval_run.py`
- `backend/app/models/eval_run_item.py`
- `backend/app/models/__init__.py`
- `backend/alembic/env.py`
- `backend/alembic/script.py.mako`
- `backend/alembic/versions/<initial_migration>.py`
- `backend/tests/test_models.py`
- `backend/tests/test_crud.py`

### 可能需要调整的现有文件

- `backend/app/db/base.py`
- `backend/app/db/session.py`
- `backend/alembic.ini`
- `README.md`
- `pyproject.toml`

---

## 十三、建议的实现顺序

为了减少返工，推荐顺序如下：

1. 补齐 `db/base.py` 与 `models/__init__.py`
2. 实现全部 ORM 模型
3. 配置 Alembic
4. 生成首个 migration
5. 执行 `alembic upgrade head`
6. 编写基础 CRUD 辅助层
7. 编写测试
8. 更新 README 中的 Phase 1 说明
9. 输出验收结果

---

## 十四、实现时最容易踩的坑

### 1. 文档路径混淆

当前权威规格实际位于：

- `Doc/文档2.MD`

不要再引用旧路径 `文档2.MD`，否则容易读错文件。

### 2. JSONB 默认值写法错误

如果默认值处理不当，容易导致：

- 多实例共享可变对象
- ORM 默认值与数据库默认值不一致

需要同时考虑 Python 侧 default 和数据库侧 server_default。

### 3. UUID / timestamp / JSONB 在 PostgreSQL 方言下的声明方式

要确保 SQLAlchemy 声明与 PostgreSQL 兼容，不要为了图省事退回不准确的通用类型。

### 4. `search_tsv` 字段与索引

虽然真正的 FTS 检索在 Phase 5/6 才用，但 Phase 1 既然定义了表结构，就应把该字段与 GIN 索引一次性建好。

### 5. `documents.current_version_id` 与 `document_versions` 的关系

这里存在循环依赖，要谨慎处理：

- 可以在 migration 中分步建立
- 模型关系声明也要避免造成初始化问题

---

## 十五、建议给 Claude Code 的执行提示

如果后续要让 Claude Code 直接实现 Phase 1，提示词应强调：

- 当前仓库已完成 Phase 0，不要重复搭脚手架
- 只实现数据库模型、Alembic、migration、基础 CRUD、测试
- 不要越过上传 / 解析 / 索引 / 检索边界
- 所有新增代码保留完整中文注释
- 输出必须包含：修改文件、运行命令、测试命令、验收方法

---

## 十六、最终结论

Phase 1 本质上是：

**把 Phase 0 的“可运行工程骨架”，升级为“具备正式持久化能力的后端骨架”。**

只要这一阶段做扎实，后续 Phase 2 到 Phase 10 的上传、解析、切分、索引、检索、更新、评测，就都有明确且稳定的数据库基础可依赖。
