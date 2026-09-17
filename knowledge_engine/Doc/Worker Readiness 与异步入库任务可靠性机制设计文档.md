# Worker Readiness 与异步入库任务可靠性机制设计文档

## 1. 文档状态

- 状态：待审计
- 适用范围：文档上传、文档替换、异步解析、清洗、chunk 切分、索引建立
- 本文只定义设计，不修改现有业务代码和数据库结构
- 权威约束来源：`Doc/文档2.MD`

## 2. 背景与已确认问题

当前异步入库流程为：

```text
前端上传
  -> FastAPI 保存原始文件
  -> PostgreSQL 创建 document/version/ingest_task
  -> Celery 将消息发送到 Redis
  -> worker 消费任务
  -> parse -> clean -> chunk -> PostgreSQL -> Qdrant/FTS
```

已通过运行环境确认：

1. worker 未启动时，任务会长期停留在 `queued`。
2. Redis 可连接不能证明 worker 在线，也不能证明关键任务已注册。
3. 宿主机 backend 与 Docker worker 混合运行时，Windows 文件路径不能在 Linux worker 中解析。
4. upload 当前先提交数据库，再投递 Celery；投递失败时 `rollback()` 无法撤销已提交事务，可能留下永久 `queued` 记录。
5. 当前没有 queued/processing 卡住任务的周期恢复机制。
6. processing 状态没有心跳，不能仅根据 `updated_at` 安全判断任务是否卡住。
7. 当前任务状态查询接口尚未实现，前端无法可靠观察失败原因和恢复过程。

## 3. 设计目标

### 3.1 必须实现

1. 完整 Docker Compose 作为唯一支持的容器运行模式，backend 和 worker 共享 `/app/storage`。
2. readiness 增加 worker 在线检查。
3. worker 在线检查与 Redis broker 检查相互独立。
4. upload/replace 派发失败后，不允许任务永久停留在 `queued`。
5. 建立 queued 卡住任务的自动恢复机制。
6. 在具备心跳、租约和幂等保护后，建立 processing 卡住任务的自动恢复机制。
7. 数据库作为任务业务状态的最终准绳。
8. 保持现有四状态：`queued`、`processing`、`completed`、`failed`。
9. 为所有状态转移提供可测试、可审计的统一模块。

### 3.2 非目标

1. 本设计不改变文档切分算法、embedding、混合检索或回答生成逻辑。
2. 本设计不引入新的消息中间件。
3. 本设计不把任务状态逻辑放入 API 路由。
4. 本设计不允许恢复器无条件重复执行非幂等 replace 流程。
5. 本设计不以 Redis 状态覆盖 PostgreSQL 业务状态。

## 4. 运行与部署约束

### 4.1 唯一支持的 Docker 运行方式

完整服务统一通过以下命令启动：

```powershell
docker compose up -d --build postgres redis qdrant backend worker beat
```

在恢复调度器尚未实现前，临时命令为：

```powershell
docker compose up -d --build postgres redis qdrant backend worker
```

若 Docker Hub 暂时不可访问，但本地已有镜像，可使用：

```powershell
docker compose up -d --no-build postgres redis qdrant backend worker
```

### 4.2 文件存储不变量

backend 和 worker 必须同时满足：

```text
STORAGE_ROOT=/app/storage
shared_storage:/app/storage
```

消息中不得传递宿主机绝对路径或 Windows 路径。推荐 Celery 参数只传 `task_id`，worker 根据数据库中的 `version_id` 查询存储定位信息。若仍传文件路径，则必须是容器内规范化路径，并在派发前验证它位于 `STORAGE_ROOT` 下。

### 4.3 禁止的运行组合

以下组合不作为支持模式：

```text
Windows 宿主机 backend + Docker worker
Docker backend + Windows 宿主机 worker
backend 与 worker 使用不同 STORAGE_ROOT
backend 与 worker 使用不同 Redis DB
```

## 5. 模块设计

建议新增深模块 `ingest_task_service`，集中隐藏状态机、派发补偿、租约、心跳和恢复复杂度。

### 5.1 外部接口

建议接口保持最小：

```python
create_and_dispatch(...)
claim(task_id, worker_id)
heartbeat(task_id, attempt_token)
complete(task_id, attempt_token, message)
fail(task_id, attempt_token, error_code, safe_message)
recover_stale_tasks(now)
get_task(task_id)
```

调用者不应自行修改 `IngestTask.status`。upload、replace、worker、恢复调度器和状态查询接口都通过该模块操作任务。

### 5.2 内部适配器

模块内部使用以下 seam：

1. PostgreSQL 任务仓储适配器：状态、租约、attempt 和行锁。
2. Celery 派发适配器：生成消息 ID、投递 ingest/replace。
3. Redis 状态镜像适配器：提供实时状态缓存，不作为最终准绳。
4. 时钟适配器：测试超时和恢复逻辑。
5. 文件存在性适配器：恢复前验证原始文件。

## 6. Worker Readiness 设计

### 6.1 接口契约

保留：

```http
GET /health
```

其响应继续严格为：

```json
{"status":"ok"}
```

不得检查任何外部依赖。

扩展：

```http
GET /api/v1/health/ready
```

建议响应：

```json
{
  "status": "ok",
  "components": {
    "postgres": {"connected": true, "latency_ms": 3.2},
    "redis": {"connected": true, "latency_ms": 1.4},
    "qdrant": {"connected": true, "latency_ms": 6.8},
    "celery_worker": {
      "connected": true,
      "latency_ms": 22.5,
      "worker_count": 1,
      "required_tasks_registered": true
    }
  }
}
```

### 6.2 在线判定

worker 可用必须同时满足：

1. 在 `CELERY_WORKER_PING_TIMEOUT_SECONDS` 内至少一个 worker 响应 `inspect ping`。
2. 至少一个响应节点注册以下任务：
   - `app.workers.ingest_worker.ingest_document_task`
   - `app.workers.ingest_worker.replace_document_task`
3. 响应 worker 消费指定 ingest 队列。

仅 Redis `PING` 成功不满足 worker readiness。

### 6.3 性能策略

`inspect registered` 比 `ping` 更重，建议：

- 每次 readiness 执行短超时 `ping`；
- 任务注册结果在进程内缓存 30 秒；
- 缓存过期后执行 `registered()`；
- 任一检查异常均转换为 `connected=false`，不向外抛 500。

### 6.4 状态码决策

保持当前兼容行为：

- HTTP 始终返回 200；
- 任一关键组件失败时 body 为 `status=degraded`。

worker 离线时将整体 readiness 标为 `degraded`。这表示系统无法完整提供上传入库能力，但不会改变 `/health` liveness。

## 7. 任务状态机

### 7.1 合法状态转移

```text
创建                     -> queued
queued + worker 原子领取 -> processing
queued + 派发永久失败     -> failed
queued + 文件不可恢复     -> failed
processing + 执行成功     -> completed
processing + 业务失败     -> failed
processing + 租约过期     -> queued（满足自动恢复条件）
processing + 超过尝试上限 -> failed
```

终态 `completed`、`failed` 不允许回退。重复消息到达终态任务时必须 no-op。

### 7.2 状态字段不变量

- `progress` 范围为 0–100。
- `queued`：无有效 lease，`finished_at=NULL`。
- `processing`：必须有 `worker_id`、`attempt_token`、`last_heartbeat_at`。
- `completed`：`progress=100`、`finished_at` 非空、`error_message=NULL`。
- `failed`：`error_message` 和 `finished_at` 非空。
- 每次状态变化必须更新 `updated_at`。
- 只有持有当前 `attempt_token` 的 worker 可以写心跳、完成或失败。

## 8. 建议数据库变更

在新 Alembic revision 中为 `ingest_tasks` 增加：

| 字段 | 类型 | 用途 |
|---|---|---|
| `celery_task_id` | varchar/uuid，可空 | 当前一次派发的 Celery 消息 ID |
| `dispatch_status` | varchar，非空 | `pending/dispatched/failed`，区分业务状态与投递状态 |
| `dispatched_at` | datetime，可空 | 最近成功投递时间 |
| `attempt_count` | integer，默认 0 | 实际执行尝试次数 |
| `recovery_count` | integer，默认 0 | 恢复器重派次数 |
| `worker_id` | varchar，可空 | 当前租约持有者 |
| `attempt_token` | uuid，可空 | fencing token，阻止旧 worker 覆盖新执行 |
| `last_heartbeat_at` | datetime，可空 | processing 存活证明 |

建议索引：

```text
(status, dispatch_status, updated_at)
(status, last_heartbeat_at)
celery_task_id
```

建议约束：

```text
attempt_count >= 0
recovery_count >= 0
status IN (queued, processing, completed, failed)
dispatch_status IN (pending, dispatched, failed)
```

不修改既有初始迁移，只增加新的 revision。

## 9. 派发失败状态补偿

### 9.1 上传任务

推荐采用“保留审计记录和源文件、版本不可检索、任务转 failed”的策略。

流程：

```text
事务 A：
  保存 document/version/task
  task.status=queued
  task.dispatch_status=pending
  version 不作为成功入库版本暴露
提交

投递 Celery
  成功：事务 B 写 dispatch_status=dispatched、celery_task_id、dispatched_at
  失败：事务 B 写 status=failed、dispatch_status=failed、error_message、finished_at
```

补偿要求：

1. 不删除源文件，以便人工或自动重派。
2. 不允许 active/current version 指向一个没有完成入库的版本。
3. 错误信息必须脱敏，不保存 Redis 密码、完整连接串或内部堆栈。
4. API 返回结构化失败；若已创建 task，响应或错误 details 应包含 `task_id`，便于查询和审计。

### 9.2 Replace 任务

沿用并强化现有策略：

- 派发失败时 task 转 `failed`；
- 新版本转 `draft`；
- `current_version_id` 保持旧版本；
- 源文件保留；
- 不停用旧 chunks，不修改 Qdrant/FTS 可见性。

### 9.3 Outbox 决策

长期推荐使用 PostgreSQL transactional outbox，从根本上消除“数据库提交成功但消息未投递”的窗口：

```text
同一事务写 ingest_task + outbox_event
独立 dispatcher 锁定 outbox_event 并发送 Celery
发送成功后标记 published
```

首期可先实现 `dispatch_status + stale queued recovery`，但它属于补偿式最终一致，不具备 outbox 的原子保证。审计时需决定首期是否直接采用 outbox。

## 10. Queued 卡住恢复机制

### 10.1 判定

任务满足以下条件时视为 stale queued：

```text
status = queued
AND updated_at < now - QUEUED_STALE_SECONDS
```

同时结合 `dispatch_status`：

- `pending`：优先恢复，说明未确认成功投递；
- `failed`：在可重试且未超上限时恢复；
- `dispatched`：阈值应更长，避免正常排队期间重复派发。

### 10.2 原子领取

恢复器使用 PostgreSQL：

```sql
SELECT ... FOR UPDATE SKIP LOCKED
```

每批限制数量，防止多个 beat 实例重复恢复同一任务。

### 10.3 恢复前检查

1. task 尚非终态。
2. document/version 存在。
3. 原始文件存在且位于共享存储。
4. task_type 属于白名单。
5. `recovery_count < MAX_RECOVERY_COUNT`。
6. 当前没有有效 processing lease。

### 10.4 处理结果

- 可恢复：生成新的 `celery_task_id`，增加 `recovery_count`，重新投递。
- 文件不存在或业务记录损坏：立即 `failed`。
- 临时 broker 错误且未超上限：保留 `queued`，记录脱敏错误，按退避等待。
- 达到上限：`failed`。

退避建议：

```text
30 秒、2 分钟、10 分钟；最多 3 次
```

## 11. Processing 卡住恢复机制

### 11.1 前置条件

processing 自动恢复必须在以下能力全部实现后启用：

1. worker 心跳；
2. lease/attempt token；
3. 原子任务领取；
4. ingest 和 replace 的重入幂等保护；
5. 旧 worker 写入 fencing；
6. 外部索引副作用的可检查或可补偿策略。

未满足时，stale processing 只能告警或标记 failed，不得自动 `.delay()`。

### 11.2 心跳与租约

建议配置：

```text
WORKER_HEARTBEAT_INTERVAL_SECONDS=30
PROCESSING_LEASE_TIMEOUT_SECONDS=180
```

worker 在长步骤之间以及长步骤执行期间更新 `last_heartbeat_at`。恢复器只处理心跳超时任务。

### 11.3 Fencing

每次领取任务生成新的 `attempt_token`。所有状态提交必须带条件：

```text
WHERE id=:task_id
  AND status='processing'
  AND attempt_token=:token
```

旧 worker 在租约失效后即使恢复，也不能覆盖新 worker 的状态。

### 11.4 Ingest 幂等策略

同一 document/version 重试时：

1. PostgreSQL chunks 使用版本范围内确定性替换或唯一约束。
2. Qdrant point ID 使用 chunk ID，upsert 可重复执行。
3. FTS 更新限定当前版本 child chunks。
4. 成功切换可见性前，旧可见数据不受影响。
5. 重试前检查是否已经完整完成；若完成则直接把任务收敛到 completed。

### 11.5 Replace 幂等策略

replace 风险高于 ingest。自动恢复前必须保证：

1. chunk diff 以固定旧版本和目标新版本为输入；
2. unchanged chunk 的向量复用可重复；
3. added chunk upsert 使用稳定 ID；
4. removed chunk 停用可重复；
5. `current_version_id` 切换采用条件更新；
6. 只有所有 PostgreSQL/Qdrant/FTS 操作完成后才切换当前版本；
7. 恢复器能识别“已完成副作用但任务状态未提交”的情况。

首期建议：stale ingest 可在幂等验证后自动恢复；stale replace 先转 failed 并告警，待增量更新幂等测试完成后再开启自动恢复。

## 12. Celery 可靠性配置

建议评估并启用：

```text
task_acks_late = true
task_reject_on_worker_lost = true
worker_prefetch_multiplier = 1
```

同时为 ingest/replace 设置合理的 soft/hard time limit。

注意：这些设置只减少消息丢失，不能替代数据库状态机和恢复器。启用 late ack 前必须先完成幂等与 fencing，否则 worker 崩溃重投可能造成并发副作用。

业务状态以 PostgreSQL 为准。若 worker 捕获异常并将业务任务写为 failed，Celery 结果状态应同步为 FAILURE 或记录明确的业务失败结果，避免 Celery SUCCESS 与业务 failed 产生歧义。

## 13. 恢复调度部署

建议在 Docker Compose 中增加独立 `beat`：

```text
celery -A app.workers.celery_app.celery_app beat --loglevel=INFO
```

不建议长期使用 `worker -B`，避免调度器与 worker 生命周期耦合。

周期建议：

```text
每 60 秒扫描 stale queued
每 60 秒扫描 stale processing
单批最多 50 条
```

恢复任务本身必须支持多实例安全运行，依赖 `FOR UPDATE SKIP LOCKED`，而不是假定只有一个 beat。

## 14. 任务状态查询接口

补齐：

```http
GET /api/v1/documents/tasks/{task_id}
```

建议响应：

```json
{
  "task_id": "uuid",
  "document_id": "uuid",
  "version_id": "uuid",
  "task_type": "ingest",
  "status": "processing",
  "dispatch_status": "dispatched",
  "message": "正在建立索引",
  "progress": 80,
  "attempt_count": 1,
  "recovery_count": 0,
  "error_message": null,
  "created_at": "...",
  "updated_at": "...",
  "finished_at": null
}
```

接口只读 PostgreSQL。Redis 可用于降低读取延迟，但发生不一致时必须返回数据库状态。

## 15. 配置项

建议增加：

```env
CELERY_WORKER_PING_TIMEOUT_SECONDS=2
CELERY_WORKER_REGISTRATION_CACHE_SECONDS=30
QUEUED_STALE_SECONDS=300
DISPATCHED_QUEUE_STALE_SECONDS=900
WORKER_HEARTBEAT_INTERVAL_SECONDS=30
PROCESSING_LEASE_TIMEOUT_SECONDS=180
TASK_RECOVERY_INTERVAL_SECONDS=60
TASK_RECOVERY_BATCH_SIZE=50
TASK_MAX_RECOVERY_COUNT=3
TASK_AUTO_RECOVER_PROCESSING=false
TASK_STATUS_REDIS_TTL_SECONDS=86400
```

生产默认关闭 processing 自动恢复，直到幂等与 fencing 验收通过。

## 16. 错误分类

任务错误至少分为：

| error_code | 是否自动重试 | 示例 |
|---|---:|---|
| `dispatch_unavailable` | 是 | Redis 短暂不可用 |
| `worker_lost` | 条件允许 | processing 心跳过期 |
| `source_file_missing` | 否 | 共享存储无原始文件 |
| `record_missing` | 否 | document/version 不存在 |
| `unsupported_task_type` | 否 | 非 ingest/replace |
| `parse_failed` | 否或人工判断 | PDF 无法解析 |
| `index_dependency_unavailable` | 是 | Qdrant 临时故障 |
| `attempts_exhausted` | 否 | 超过恢复上限 |

数据库和 API 只暴露脱敏后的 `safe_message`；完整堆栈进入日志并关联 `task_id/celery_task_id/attempt_token`。

## 17. 可观测性

所有任务日志使用结构化字段：

```text
task_id
document_id
version_id
task_type
celery_task_id
attempt_count
recovery_count
worker_id
attempt_token
status_transition
```

建议指标：

```text
ingest_tasks_total{status,task_type}
ingest_dispatch_failures_total{task_type,error_code}
ingest_recoveries_total{task_type,reason,result}
ingest_task_duration_seconds{task_type}
ingest_task_queue_age_seconds{task_type}
celery_workers_online
celery_required_tasks_registered
```

告警：

1. worker 在线数为 0；
2. 关键任务未注册；
3. queued 最老任务超过阈值；
4. processing 心跳过期；
5. 派发失败率升高；
6. 恢复次数达到上限。

## 18. 安全要求

1. 健康检查不返回 worker 主机内部信息、Redis URL 或凭据。
2. `error_message` 不保存完整连接串和堆栈。
3. 恢复器只派发白名单任务，不根据数据库字符串动态导入任意函数。
4. 文件路径必须验证位于 `STORAGE_ROOT` 内，防止路径穿越。
5. 管理性手动恢复接口如后续增加，必须鉴权并记录审计日志。

## 19. 测试与验收矩阵

### 19.1 Readiness

| 场景 | 预期 |
|---|---|
| 所有依赖和 worker 在线，任务已注册 | `status=ok`，四组件 connected=true |
| Redis 在线、worker 离线 | `status=degraded`，redis=true，celery_worker=false |
| worker 在线但 ingest/replace 未注册 | `status=degraded` |
| inspect 超时或异常 | 在配置超时内返回 degraded，不返回 500 |
| `/health` | 始终严格返回 `{"status":"ok"}` |

### 19.2 派发补偿

| 场景 | 预期 |
|---|---|
| upload 派发成功 | queued + dispatched |
| upload `.delay()` 抛异常 | failed，finished_at/error_message 非空，源文件和记录一致 |
| replace 派发失败 | failed，新版本 draft，旧版本仍可见 |
| 补偿事务临时失败 | stale queued 恢复器可识别 |
| 异常含凭据 | API 与数据库均不泄露凭据 |

### 19.3 Queued 恢复

| 场景 | 预期 |
|---|---|
| 未超过阈值 | 不处理 |
| stale 且文件完整 | 只重派一次 |
| 两个恢复器并发扫描 | 只有一个获得任务 |
| 文件不存在 | failed，不重派 |
| 达到恢复上限 | failed，后续不再处理 |
| task 已变 processing/终态 | 恢复器 no-op |

### 19.4 Processing 恢复

| 场景 | 预期 |
|---|---|
| 心跳新鲜 | 不恢复 |
| 长任务持续心跳 | 不误判 |
| 心跳过期 | 按 task_type 策略恢复或失败 |
| 旧 worker 恢复后提交 | fencing 拒绝旧 token |
| 重复 ingest | PostgreSQL/Qdrant/FTS 最终一致，无重复可见 chunk |
| stale replace 且自动恢复关闭 | failed/告警，不自动重派 |

### 19.5 状态接口

覆盖 queued、processing、completed、failed、不存在、非法 UUID、恢复期间查询和数据库/Redis 不一致。

## 20. 分阶段实施计划

### Phase A：部署与可见性

1. 统一完整 Docker Compose。
2. readiness 增加 worker ping 和关键任务注册检查。
3. 补齐任务状态查询接口。
4. 更新健康检查与集成测试。

### Phase B：派发一致性与 queued 恢复

1. 引入统一任务状态模块。
2. 新增派发元数据、attempt/recovery 字段和扫描索引。
3. 统一 upload/replace 派发失败补偿。
4. 增加独立 beat。
5. 实现 stale queued 原子恢复。

### Phase C：processing 租约

1. 增加 worker 心跳、worker_id、attempt_token。
2. 实现原子领取和 fencing。
3. 扩大最外层异常补偿范围。
4. 增加 processing 告警，暂不自动恢复 replace。

### Phase D：幂等与自动恢复

1. 验证 ingest 重入幂等。
2. 验证 replace 增量更新重入幂等。
3. 启用 late ack、worker lost 重投。
4. 分 task_type 开启 processing 自动恢复。

## 21. 预计修改文件

```text
backend/app/config.py
backend/app/dependencies.py
backend/app/api/health.py
backend/app/api/documents.py
backend/app/schemas/ingest_task.py
backend/app/models/ingest_task.py
backend/app/services/upload_service.py
backend/app/services/update_service.py
backend/app/services/ingest_task_service.py（新增）
backend/app/workers/celery_app.py
backend/app/workers/ingest_worker.py
backend/alembic/versions/<new_revision>.py（新增）
docker-compose.yml
backend/tests/test_health.py
backend/tests/test_integration.py
backend/tests/test_upload.py
backend/tests/test_ingest_worker.py
以及任务状态/恢复机制专项测试
```

## 22. 审计决策清单

代码实施前请确认：

- [ ] worker 离线是否令整体 readiness 为 degraded。
- [ ] readiness 是否同时验证关键任务注册。
- [ ] 是否接受新增独立 beat 服务。
- [ ] upload 派发失败后是否保留源文件和审计记录。
- [ ] upload 未完成入库前，版本如何避免被视为有效当前版本。
- [ ] 首期采用补偿式恢复，还是直接实施 transactional outbox。
- [ ] queued 最大恢复次数和退避参数。
- [ ] 是否接受新增 dispatch/attempt/heartbeat/lease 字段。
- [ ] processing 自动恢复是否默认关闭。
- [ ] stale replace 是否先标记失败并人工处理。
- [ ] 是否补齐 PostgreSQL/Redis 任务状态双写。
- [ ] 派发失败 API 返回 500，还是返回带 task_id 的可查询失败响应。
- [ ] Celery late ack 是否等幂等/fencing 完成后再启用。

## 23. 当前运行基线

本次审计前已用 Docker Compose 启动：

```text
postgres: healthy
redis: healthy
qdrant: healthy
backend: running
worker: running
```

Celery 检查结果：

```text
1 node online
app.workers.ingest_worker.ingest_document_task 已注册
app.workers.ingest_worker.replace_document_task 已注册
```

现有 `/api/v1/health/ready` 只返回 PostgreSQL、Redis、Qdrant，尚未包含 worker；该行为是本设计 Phase A 的首个代码改动目标。
