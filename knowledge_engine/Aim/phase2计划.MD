# Phase 2 实施计划（文件上传与存储）

> 本计划基于当前仓库 **Phase 0 已完成**、并以 **Phase 1 将完成数据库模型与迁移** 为前提编写。
> 
> 本阶段目标是：在不越过规格边界的前提下，完成 **文件上传入口、原始文件存储、file_hash 计算、document/version/task 创建、Celery 任务投递与 task_id 返回**。

---

## 一、Phase 2 的目标

根据权威规格，Phase 2 的唯一目标是：

**支持文件上传，并把“上传一个新文档”这件事完整落地到存储层、数据库层和异步任务入口层。**

这意味着 Phase 2 要解决的是：

- 用户如何上传文件
- 文件如何落盘保存
- 如何识别文件类型与基本元数据
- 如何创建 `document`
- 如何创建 `document_version`
- 如何创建 `ingest_task`
- 如何把任务投递给 Celery worker
- 如何把 `task_id` 返回给用户

但 Phase 2 还**不是**真正的“文档入库完成阶段”。
真正的解析、清洗、切分、embedding、索引写入，仍属于 Phase 3 ~ 5。

---

## 二、必须严格遵守的范围边界

### 2.1 本阶段必须完成

按照规格，Phase 2 必须完成：

1. 实现 `/documents/upload`
2. 保存文件到本地 storage（本项目第一版固定本地文件存储）
3. 计算 `file_hash`
4. 创建 `document` 和 `document_version`
5. 创建 `ingest_task`
6. 投递 Celery 入库任务
7. 返回 `task_id`

### 2.2 本阶段绝对不要提前实现

本阶段不要越界实现以下内容：

- 不要实现 PDF / Markdown / TXT 解析逻辑
- 不要实现 cleaner
- 不要实现 chunk 切分
- 不要实现 embedding 生成
- 不要实现 Qdrant 写入
- 不要实现 PostgreSQL FTS 建索引
- 不要实现 query pipeline
- 不要实现 replace 接口
- 不要实现 chunk diff
- 不要实现真实的入库业务处理链路

### 2.3 关于 Celery 的边界

本阶段可以做：

- 定义 worker 入口函数
- 建立 Celery app
- 让上传接口把任务成功投递出去

本阶段不要做：

- 在 worker 中实现真实解析/清洗/切分/索引逻辑
- 把后续 Phase 的业务偷偷塞进 worker

worker 允许先写成最小占位流程，例如：

- 接到任务
- 更新状态为 `processing`
- 记录 TODO / 占位日志
- 暂时标记为 `completed` 或保留明确占位策略

但这里建议谨慎：如果还没有 Phase 3 之后的真实链路，最好明确区分“任务已投递”和“真实入库未完成”的边界，避免误导。

---

## 三、当前仓库现状与 Phase 2 的前置条件

### 3.1 当前已具备的基础

基于现有仓库内容，当前已经具备：

- FastAPI 应用骨架
- PostgreSQL / Redis / Qdrant / backend 的 docker 编排
- `config.py` 配置中心
- `db/session.py` 数据库连接工厂
- `dependencies.py` 共享依赖注入
- 健康检查接口与基础测试结构

### 3.2 Phase 2 的关键前提

Phase 2 的正确落地，**依赖 Phase 1 先完成**：

- `documents` 表已存在
- `document_versions` 表已存在
- `ingest_tasks` 表已存在
- Alembic migration 已可执行
- 基础 CRUD 已具备

如果 Phase 1 还没完成，就不要直接进入 Phase 2 编码。
因为上传接口不是单纯接文件，它必须把数据库记录一并创建出来。

---

## 四、Phase 2 的实施原则

### 4.1 上传接口只负责“创建新 document”

这一点是硬约束：

- `POST /api/v1/documents/upload` **只能创建新 document**
- 不能通过标题自动归并到旧文档
- 不能通过 `document_id` 指定挂到已有文档
- 新版本创建只能在后续 `replace` 接口实现

这是整个版本体系的基础，不能在 Phase 2 偷偷改语义。

### 4.2 文件必须先保存，再建库记录

推荐顺序：

1. 收到上传文件
2. 基础校验文件类型
3. 读取 bytes
4. 计算 `file_hash`
5. 生成稳定存储路径
6. 保存文件到 storage
7. 创建 `document`
8. 创建 `document_version`
9. 创建 `ingest_task`
10. 投递 Celery 任务
11. 返回 `document_id / version_id / task_id`

不要先写数据库再决定文件是否能存下来，否则容易出现脏记录。

### 4.3 文件存储路径必须可回溯

第一版已约定本地文件存储，因此要遵守：

- 文件必须保存到配置定义的 storage 根目录下
- 路径中必须包含 `document_id` 和 `version_id` 或等价唯一标识
- 不允许只按原始文件名直接落盘
- 替换新版本时不能覆盖旧版本文件

### 4.4 路由层保持极薄

`/documents/upload` 路由不应直接承担以下职责：

- 文件系统路径拼装
- 哈希计算实现细节
- 数据库事务细节
- Celery 投递细节

这些都应下沉到 service 层，例如：

- `storage_service.py`
- `upload_service.py`（如果需要新增）
- `hash_utils.py`
- `workers/celery_app.py`

---

## 五、建议的实现拆分

建议把 Phase 2 拆成 7 个步骤执行。

---

## 六、Step 1：补齐配置项

### 目标

让上传、存储与任务投递依赖的配置都能从 `.env` 读取。

### 建议新增配置

至少应补充：

- `storage_root`
- `max_upload_size_mb`
- `allowed_upload_extensions`
- `allowed_mime_types`（如果你想在配置层管理）
- `celery_broker_url`（通常可基于 Redis 派生）
- `celery_result_backend`（可选）

### 实现要求

- 配置统一放入 `backend/app/config.py`
- `.env.example` 同步补齐
- 保持本地运行与 Docker 运行都可配置

---

## 七、Step 2：实现文件存储服务

### 目标

提供统一的原始文件落盘能力。

### 推荐文件

- `backend/app/services/storage_service.py`

### 建议职责

1. 确保 storage 根目录存在
2. 生成稳定且可追溯的存储路径
3. 保存原始文件
4. 返回实际保存路径
5. 提供基础文件存在性检查（可选）

### 建议存储结构

可以采用类似结构：

```text
storage/
  documents/
    <document_id>/
      <version_id>/
        original.pdf
```

或：

```text
storage/
  <document_id>/
    <version_id>_<safe_filename>.pdf
```

关键不是形式，而是要满足：

- 路径稳定
- 可回溯
- 不覆盖旧版本
- 不仅依赖原始文件名

### 注意点

- 文件名需要做基础安全处理
- 避免路径穿越问题
- 保存失败时要能明确报错

---

## 八、Step 3：实现哈希工具与上传校验

### 目标

完成 `file_hash` 计算与上传文件基础校验。

### 推荐文件

- `backend/app/utils/hash_utils.py`
- `backend/app/schemas/upload.py`

### 最低要求

1. `file_hash` 基于原始文件 bytes 的 SHA-256
2. 支持的文件类型至少覆盖：
   - PDF
   - Markdown
   - TXT
3. 拒绝不支持的文件类型
4. 对上传文件大小做基础限制

### 注意点

- 这里的哈希是文件级哈希，不是 chunk 哈希
- `chunk_hash` 不属于本阶段
- MIME 类型判断和扩展名判断最好组合使用，不要只信任其一

---

## 九、Step 4：实现上传领域服务

### 目标

把上传流程的核心业务从 route 中拆出来。

### 推荐文件

可以新增一个服务，例如：

- `backend/app/services/upload_service.py`

如果你不想新增独立服务，也至少要把逻辑组织清楚，不要堆在 route 里。

### 该服务建议负责

1. 校验上传文件
2. 计算 `file_hash`
3. 保存原始文件
4. 在数据库中创建 `document`
5. 创建 `version_no = 1` 的 `document_version`
6. 创建 `ingest_task(status=queued)`
7. 提交事务
8. 投递 Celery 任务
9. 组装返回结果

### 推荐事务边界

建议将以下内容放在同一事务内：

- 创建 `document`
- 创建 `document_version`
- 创建 `ingest_task`

文件存储建议在事务之前完成，或至少保证失败可回滚策略清晰。

### 关于失败处理

如果数据库事务失败，而文件已保存：

- 可以删除刚落盘的文件
- 或记录为失败并人工清理

第一版建议优先实现“失败时尝试清理文件”。

---

## 十、Step 5：实现上传接口

### 目标

落地 `/api/v1/documents/upload`。

### 推荐文件

- `backend/app/api/upload.py`
- `backend/app/api/__init__.py`

### 接口要求

请求应支持：

- `file`
- `doc_type`
- `title`
- `security_domain`
- `tags`
- `publish_date`
- `effective_date`
- `version_status`

### 返回结构

应符合规格：

```json
{
  "document_id": "uuid",
  "version_id": "uuid",
  "task_id": "uuid",
  "status": "queued"
}
```

### 错误处理

至少需要覆盖：

- 文件类型不支持 → `unsupported_file_type`
- 参数不合法 → `invalid_request`
- 文件为空或超大小 → `invalid_request`
- 内部错误 → `internal_error`

### 重要边界

- 上传接口不能接收 `document_id`
- 上传接口不能复用旧文档
- 上传接口不能做 replace 语义

---

## 十一、Step 6：接入 Celery 与任务投递

### 目标

让上传后可以把任务异步投递出去。

### 推荐文件

- `backend/app/workers/celery_app.py`
- `backend/app/workers/ingest_worker.py`

### 本阶段建议实现

1. 创建 Celery app
2. 配置 broker（通常 Redis）
3. 定义 `ingest_document_task(...)`
4. 上传成功后调用 `.delay(...)` 或等价方式投递任务

### worker 在本阶段的合理实现范围

由于真实解析链路属于 Phase 3+，本阶段 worker 可以：

- 接收参数：`document_id`、`version_id`、`task_id`、`file_path`
- 更新任务状态为 `processing`
- 记录日志说明“后续 Phase 实现真实入库逻辑”

关于最终状态，有两种可选策略：

#### 策略 A：保留 queued / processing，不伪装完成
优点：语义更真实。
缺点：当前用户看到的任务不会自然结束。

#### 策略 B：先做明确占位完成
优点：上传闭环更完整。
缺点：容易让人误解“真实入库已经完成”。

更建议采用 **策略 A 或带明确占位标记的 processing/failed**，并在 README 中写清楚当前限制。

---

## 十二、Step 7：测试与验收

### 目标

确保上传流程在当前阶段真正可用。

### 至少要补的测试

#### 1. 上传接口测试

建议新增：

- `backend/tests/test_upload.py`

至少覆盖：

- 上传 PDF 成功
- 返回 `document_id / version_id / task_id`
- 参数缺失时报错
- 不支持的文件类型时报错
- 不允许通过 upload 传 `document_id`

#### 2. 存储层测试

可覆盖：

- 文件成功保存到 storage
- 路径包含 document/version 标识
- 保存失败时正确报错

#### 3. 数据库集成测试

至少验证：

- 成功上传后数据库存在 `document`
- 存在 `document_version`
- 存在 `ingest_task`

#### 4. 任务投递测试

至少验证：

- 上传成功后 Celery 投递被调用
- 或在集成环境中确实生成任务消息

如果不想在单元测试中真的启动 worker，可以 mock Celery 的投递调用。

### 验收命令建议

```bash
# 1. 启动基础设施
docker compose up -d postgres redis qdrant

# 2. 如需完整上传链路测试，再启动 backend 与 worker
docker compose up -d backend

# 3. 执行数据库迁移
cd backend
alembic upgrade head

# 4. 跑默认测试
pytest

# 5. 跑上传相关测试
pytest backend/tests/test_upload.py
```

### Phase 2 验收标准

必须达到：

- 可以上传 PDF
- 数据库能看到 `document / version / task`
- 文件能在 storage 中找到
- `/upload` 不会把文件挂到旧 `document` 下

---

## 十三、推荐文件改动清单

以下是执行 Phase 2 时大概率会涉及的文件。

### 需要新增或完善的文件

- `backend/app/api/upload.py`
- `backend/app/schemas/upload.py`
- `backend/app/services/storage_service.py`
- `backend/app/services/upload_service.py`
- `backend/app/utils/hash_utils.py`
- `backend/app/workers/celery_app.py`
- `backend/app/workers/ingest_worker.py`
- `backend/tests/test_upload.py`

### 可能需要调整的现有文件

- `backend/app/api/__init__.py`
- `backend/app/config.py`
- `.env.example`
- `docker-compose.yml`
- `README.md`
- `pyproject.toml`

### 如果需要补充 Docker 支持

可能还需要：

- `backend/Dockerfile`
- worker 启动命令配置
- compose 中增加 `worker` 服务

---

## 十四、建议的实现顺序

推荐顺序如下：

1. 补齐配置项
2. 实现 storage service
3. 实现 hash 工具
4. 实现 upload schema
5. 实现 upload service
6. 实现 upload route
7. 接入 Celery app 与 ingest worker
8. 编写上传测试
9. 更新 README 的 Phase 2 说明
10. 进行验收

---

## 十五、实现时最容易踩的坑

### 1. 错把 upload 做成“新版本上传”

这是最危险的边界错误。

必须记住：

- `upload = 新 document`
- `replace = 已有 document 的新 version`

二者在接口语义上严格分离。

### 2. 文件先写库、后保存，导致脏数据

如果先建数据库记录，再保存文件，文件一旦失败，就会残留无效记录。

### 3. 文件名和存储路径设计过于草率

如果只按原始文件名保存：

- 很容易重名覆盖
- 不利于版本追踪
- 后续 replace 很难管理

### 4. 把 Celery worker 误写成真实入库流程

Phase 2 只能搭好异步入口，不能把 Phase 3~5 的内容提前塞进去。

### 5. upload 路由写太重

如果把 hash、存储、事务、Celery 都写进 route，后续维护会很痛苦。

### 6. 忽视错误响应结构统一

从 Phase 2 开始就应尽量遵循统一错误响应：

```json
{
  "error": {
    "code": "string",
    "message": "string",
    "details": {}
  }
}
```

否则后面再统一会返工。

---

## 十六、建议给 Claude Code 的执行提示

如果后续要让 Claude Code 直接实现 Phase 2，提示词应强调：

- 当前仓库已经完成 Phase 0，且 Phase 1 应已完成
- 只实现上传、文件存储、file_hash、document/version/task 创建、Celery 投递
- 不要提前实现解析、切分、索引、检索逻辑
- upload 只能创建新 document，不能变成 replace
- 所有新增代码保留完整中文注释
- 输出必须包含：修改文件、运行命令、测试命令、验收方法

---

## 十七、最终结论

Phase 2 的本质是：

**把“数据库地基”进一步升级为“可接收真实知识文件的异步入库入口”。**

完成本阶段后，系统虽然还不能真正把内容解析入库，但已经具备了：

- 对外接收知识文件
- 保存原始文档
- 建立文档与版本记录
- 建立任务记录
- 把后续入库工作异步化

这正是 Phase 3 开始实现解析与清洗的前提。
