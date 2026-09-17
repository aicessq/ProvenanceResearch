# Phase 9 实施计划（知识更新、修改、删除）

> 本计划基于当前仓库 **Phase 0~8 已完成或将完成** 的前提编写。
> 
> 本阶段目标是：在不越过规格边界的前提下，完成 **文档替换接口、file_hash 对比、chunk_hash diff、未变化 chunk 复用、软删除以及 Qdrant / PostgreSQL FTS 同步更新**。

---

## 一、Phase 9 的目标

根据权威规格，Phase 9 的唯一目标是：

**让知识库从“可一次性入库和问答”，升级为“可持续维护、替换、删除和增量更新”。**

这一阶段要解决的问题是：

- 如何替换已有 document 的新版本
- 如何用 `file_hash` 判断文件是否 unchanged
- 如何用 `chunk_hash` 做增量 diff
- 如何只为新增或变更 child chunk 重新 embedding
- 如何让删除变成软删除
- 如何让 Qdrant 与 FTS 同步更新可见性
- 如何支持法规版本状态（`active / expired / amended`）

---

## 二、必须严格遵守的范围边界

### 2.1 本阶段必须完成

按照规格，Phase 9 必须完成：

1. 实现文档替换接口
2. 实现 `file_hash` 对比
3. 实现 `chunk_hash diff`
4. 新增 chunk 入库
5. 删除 chunk 软删除
6. 未变化 chunk 复用旧 embedding
7. Qdrant / PostgreSQL FTS 同步更新
8. 支持法规 `active / expired / amended` 状态

### 2.2 本阶段不要提前实现

本阶段不要越界实现以下内容：

- 不要实现自动从互联网同步法规
- 不要实现复杂版本比较报告页面
- 不要做全库重建作为默认路径

### 2.3 本阶段最重要的硬约束

必须严格遵守：

- 更新必须采用 **chunk diff**
- 不允许因为替换一个 document 而全库重建
- 不允许对 unchanged child chunk 重新 embedding
- 默认检索仍只面向 active current version

---

## 三、当前仓库现状与 Phase 9 的前置条件

### 3.1 当前已具备的基础

进入 Phase 9 前，理论上应已具备：

- Phase 2：upload 流程
- Phase 4：child chunk / parent chunk / chunk_hash
- Phase 5：Qdrant 与 FTS 索引能力
- Phase 8：query/answer 已可用
- `documents.current_version_id` / `document_versions.version_status` / `chunks.is_active` 等状态字段已存在

### 3.2 Phase 9 的关键依赖

本阶段应依赖：

- 已有 `file_hash` 工具
- 已有 `chunk_hash` 工具
- chunk 持久化与 metadata 组织已稳定
- vector_store / keyword_store 已支持可见性更新

如果 Phase 4 和 5 还不稳定，本阶段很难正确实现增量更新。

---

## 四、Phase 9 的实施原则

### 4.1 upload 与 replace 必须严格分离

- `upload`：创建新 document
- `replace`：为已有 document 创建新 version

不能把 replace 语义混进 upload。

### 4.2 diff 主体是 child chunk，不是 parent chunk

即使 parent 重建了，只要 child `chunk_hash` 不变，就必须视为 unchanged。

### 4.3 unchanged child 要复用索引能力

本阶段最关键的效率点在于：

- unchanged child 不重跑 embedding
- 不重建向量数据
- 不重复更新关键词索引主内容

但数据库层面仍要按新版本保留对应记录。

### 4.4 删除优先软删除

不要把 delete 做成默认物理删除。
应该优先：

- `documents.status = deleted`
- `chunks.is_active = false`
- Qdrant payload `is_active = false`
- FTS 检索可见性关闭

---

## 五、建议的实现拆分

建议把 Phase 9 拆成 7 个步骤执行。

---

## 六、Step 1：实现 replace 接口

### 目标

支持为已有 document 创建新版本。

### 推荐文件

- `backend/app/api/documents.py`
- `backend/app/schemas/document.py`
- `backend/app/services/update_service.py`

### 最低要求

1. 接收新文件
2. 校验 `document_id` 是否存在
3. 计算新文件 `file_hash`
4. 判断是否 unchanged
5. 若有变化，创建新 `document_version`
6. 创建 replace 类型 `ingest_task`
7. 投递异步更新任务

### 注意点

- unchanged 时不得创建新 version
- 返回业务错误 `file_unchanged`

---

## 七、Step 2：实现 file_hash 对比

### 目标

在 version 层快速判断文件是否变化。

### 推荐文件

- `backend/app/utils/hash_utils.py`
- `backend/app/services/update_service.py`

### 最低要求

1. 读取原始文件 bytes
2. 计算 SHA-256
3. 与 current version 的 `file_hash` 比较
4. unchanged 时快速终止更新链路

### 注意点

- `file_hash` 只是快速判定文件级未变
- 真正的增量更新仍依赖后续 `chunk_hash diff`

---

## 八、Step 3：实现 chunk_hash diff

### 目标

对旧版本与新版本的 child chunk 进行增量比较。

### 推荐文件

- `backend/app/services/update_service.py`

### 设计要求

1. 只比较 child chunk
2. 读取旧 current version 的 active child chunks
3. 生成新版本 child chunks
4. 构建 `old_map` / `new_map`（key = `chunk_hash`）
5. 计算：
   - `added`
   - `removed`
   - `unchanged`
   - `updated`（本质可视为 removed + added）

### 注意点

- `chunk_index` 不能作为 diff 主键
- `chunk_hash` 才是唯一依据
- parent 内容变化但 child hash 不变时，child 视为 unchanged

---

## 九、Step 4：实现增量持久化与索引复用

### 目标

按 diff 结果执行最小变更更新。

### 推荐文件

- `backend/app/services/update_service.py`
- `backend/app/services/index_service.py`
- `backend/app/services/vector_store.py`
- `backend/app/services/keyword_store.py`

### 处理规则

#### added

- 新建 chunk 记录
- 生成 embedding
- 写入 Qdrant
- 更新 FTS

#### removed

- 旧 chunk `is_active=false`
- Qdrant payload `is_active=false`
- FTS 可见性关闭

#### unchanged

- 在新 version 下保留新的数据库记录
- 复用旧 embedding / 旧索引能力
- 不重新 embedding

#### updated

- 可视为 removed + added

### 注意点

- unchanged 复用是本阶段成败关键
- 不要偷懒把 unchanged 当 added 全重建

---

## 十、Step 5：实现软删除接口

### 目标

让 document 删除后默认不再被检索，但保留历史记录。

### 推荐文件

- `backend/app/api/documents.py`
- `backend/app/services/update_service.py`

### 最低要求

1. `DELETE /api/v1/documents/{document_id}`
2. 将 `documents.status` 标为 `deleted`
3. 将相关 active chunks 标为 `is_active=false`
4. 将 Qdrant payload `is_active=false`
5. 让 FTS 记录失去可见性

### 幂等要求

- 已删除文档再次删除仍返回成功
- 返回状态仍为 `deleted`

---

## 十一、Step 6：支持法规版本状态与 current version 切换

### 目标

把版本语义真正落地到检索作用域。

### 推荐文件

- `backend/app/services/update_service.py`
- `backend/app/services/crud_service.py`

### 最低要求

1. 支持 `version_status`：
   - `active`
   - `expired`
   - `amended`
2. replace 成功后原子更新 `documents.current_version_id`
3. 默认检索只看 active current version

### 注意点

- 不能出现同一个 document 默认同时命中多个 current version
- 状态切换逻辑要与 query 默认过滤保持一致

---

## 十二、Step 7：测试与验收

### 建议新增测试文件

- `backend/tests/test_update_service.py`
- `backend/tests/test_document_replace_api.py`
- `backend/tests/test_document_delete_api.py`

### 至少要覆盖的测试

#### 1. replace

- unchanged 文件返回 `file_unchanged`
- changed 文件创建新 version
- 新任务被创建

#### 2. chunk diff

- added / removed / unchanged 分类正确
- unchanged chunk 不重新 embedding

#### 3. soft delete

- 删除后 document 不可检索
- chunk `is_active=false`
- payload `is_active=false`

#### 4. current version

- replace 后 `current_version_id` 正确切换
- 默认检索只看新版本

### 验收命令建议

如果使用 conda：

```bash
conda run -n rag_sec_phase1 pytest backend/tests/test_update_service.py -m integration
conda run -n rag_sec_phase1 pytest backend/tests/test_document_replace_api.py -m integration
conda run -n rag_sec_phase1 pytest backend/tests/test_document_delete_api.py -m integration
```

如果使用 venv：

```bash
.venv\Scripts\python -m pytest backend/tests/test_update_service.py -m integration
.venv\Scripts\python -m pytest backend/tests/test_document_replace_api.py -m integration
.venv\Scripts\python -m pytest backend/tests/test_document_delete_api.py -m integration
```

### Phase 9 验收标准

必须达到：

- 替换文件后不会全库重建
- 未变化 chunk 不重新 embedding
- 删除文件后无法被检索
- 旧版本可以保留
- 默认只检索 active 当前版本

---

## 十三、推荐文件改动清单

### 需要新增或完善的文件

- `backend/app/services/update_service.py`
- `backend/app/api/documents.py`
- `backend/app/schemas/document.py`
- `backend/tests/test_update_service.py`
- `backend/tests/test_document_replace_api.py`
- `backend/tests/test_document_delete_api.py`

### 可能需要调整的现有文件

- `backend/app/services/index_service.py`
- `backend/app/services/vector_store.py`
- `backend/app/services/keyword_store.py`
- `backend/app/services/crud_service.py`
- `backend/app/workers/ingest_worker.py`
- `README.md`

---

## 十四、建议的实现顺序

1. 实现 replace 接口
2. 实现 file_hash 对比
3. 实现 chunk_hash diff
4. 实现增量持久化与索引复用
5. 实现 soft delete
6. 实现 current version 切换
7. 编写测试
8. 更新 README
9. 验收

---

## 十五、实现时最容易踩的坑

### 1. 把 replace 做成全量重建

这是对规格最直接的违背。

### 2. 用 chunk_index 做 diff

这会导致大量误判。

### 3. unchanged chunk 仍重新 embedding

这会直接破坏增量更新设计初衷。

### 4. 删除只改数据库，不改索引可见性

这样会出现“逻辑删除了但仍能搜到”的严重错误。

---

## 十六、最终结论

Phase 9 的本质是：

**把“可入库、可问答”的知识库，升级为“可持续更新、替换、删除且不会无谓重建”的生产化知识库。**

完成本阶段后，系统将真正具备长期维护能力。
