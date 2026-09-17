# Celery ingest 任务未注册修复建议

## 1. 问题现象

在 Docker 环境下，前端上传文件后，`/api/v1/documents/upload` 返回成功，例如：

```json
{
  "document_id": "01fd5659-2119-42ec-b722-ce1908b7950d",
  "version_id": "cdb79ad7-d497-443e-91f8-c8259a6471a8",
  "task_id": "2b932dc1-53c0-479e-b568-f60f583e75f3",
  "status": "queued"
}
```

但 worker 日志出现如下报错：

```text
Received unregistered task of type 'app.workers.ingest_worker.ingest_document_task'.
The message has been ignored and discarded.
KeyError: 'app.workers.ingest_worker.ingest_document_task'
```

这说明：

1. 后端 API 已经成功把任务投递到 Redis / Celery。
2. worker 进程本身也已经正常启动并连接到 Redis。
3. 但是 worker 启动时**没有加载 `app.workers.ingest_worker` 模块**，导致任务名未注册，消息被直接丢弃。

---

## 2. 根因分析

问题根因位于：

- `backend/app/workers/celery_app.py`

修复前的 `Celery(...)` 初始化仅包含：

- `broker`
- `backend`

但没有做以下任一动作：

- `include=[...]` 显式包含任务模块
- `autodiscover_tasks(...)` 自动发现任务模块
- 额外 import `ingest_worker` 以触发 `@celery_app.task(...)` 注册

因此 worker 日志中的 `[tasks]` 区域为空，最终在消费到 `app.workers.ingest_worker.ingest_document_task` 时抛出未注册错误。

---

## 3. 修复方案

本次采用**最小修复**：

在 `backend/app/workers/celery_app.py` 中为 Celery 增加显式任务包含：

```python
celery_app = Celery(
    "cybersec_rag_agent",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.ingest_worker"],
)
```

这样 worker 启动时会主动加载 `app.workers.ingest_worker`，从而注册：

- `app.workers.ingest_worker.ingest_document_task`

该方案优点：

1. 改动小，不影响现有任务调用方式。
2. 与当前项目“显式、可控”的风格一致。
3. 后续如果增加 `replace` / `reindex` 等 worker 模块，也可以继续在 `include` 中追加。

---

## 4. 已执行修复

已修改文件：

- `backend/app/workers/celery_app.py`

修复内容：

- 为 `Celery(...)` 增加 `include=["app.workers.ingest_worker"]`

---

## 5. 修复后的验证步骤

### 步骤 1：重建并重启容器

在项目根目录执行：

```powershell
docker compose down
docker compose up -d --build
```

### 步骤 2：确认 worker 启动正常

```powershell
docker compose logs -f worker
```

重点观察：

1. worker 启动时 `[tasks]` 区域不应再为空。
2. 应能看到：

```text
app.workers.ingest_worker.ingest_document_task
```

### 步骤 3：重新上传文件

注意：**修复前已经被丢弃的任务不会自动恢复**，必须重新上传一次文件，重新生成新的 `task_id`。

### 步骤 4：观察 worker 是否开始处理任务

理想情况下，重新上传后应看到类似流程：

- 收到 ingest 任务
- 开始解析文档
- 开始清洗 / chunk 切分
- 开始 PostgreSQL / Qdrant / FTS 建索引
- 任务完成或明确报出后续业务错误

---

## 6. 后续建议

### 建议 1：为 worker 启动增加任务注册自检

可在后续优化中增加一条启动自检，确保关键任务名已注册，否则启动时直接报警，避免“上传成功但任务静默丢弃”。

### 建议 2：补一条针对 Celery 注册的测试

建议增加一条轻量测试，例如断言：

- Celery app 已注册 `app.workers.ingest_worker.ingest_document_task`

这样在未来调整 worker 结构或模块路径时，可以更早发现问题。

### 建议 3：如果后续 worker 模块增多，可统一集中声明

当前只修复 ingest 任务即可；如果后续新增：

- `replace`
- `reindex`
- 其他异步任务

建议统一在 `celery_app.py` 中维护 `include=[...]` 列表，避免不同模块注册方式不一致。

---

## 7. 本次修复结论

本次问题不是上传接口失败，也不是 Redis/Celery 服务不可用，而是：

> worker 已启动，但没有注册 `ingest_document_task`，导致任务消息被消费端判定为未知任务并直接丢弃。

当前修复通过在 `celery_app.py` 中显式包含 `app.workers.ingest_worker` 模块解决该问题。
