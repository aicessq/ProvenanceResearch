# Phase 5 实施计划（Embedding、Reranker 与索引）

> 本计划基于当前仓库 **Phase 0 已完成、Phase 1 已完成，且 Phase 2~4 将完成上传、解析、清洗、切分与 chunk 落库** 的前提编写。
> 
> 本阶段目标是：在不越过规格边界的前提下，完成 **本地 embedding 与 reranker 封装、Qdrant upsert、PostgreSQL FTS 关键词索引、metadata payload 组织、is_active 可见性支持，以及入库后自动建立索引**。

---

## 一、Phase 5 的目标

根据权威规格，Phase 5 的唯一目标是：

**把 Phase 4 生成并落库的 child chunk，真正写入后续检索系统所需的索引层。**

这一阶段要解决的问题是：

- 如何加载本地 embedding 模型
- 如何为 child chunk 生成向量
- 如何加载本地 reranker 模型并封装接口
- 如何把 child chunk 写入 Qdrant
- 如何为 PostgreSQL 建立关键词检索字段
- 如何组织统一 metadata payload
- 如何支持 `is_active` 检索可见性
- 如何在入库任务中自动完成索引建立

但 Phase 5 仍然**不是**查询阶段。
虽然索引已经建立，但检索 API、RRF、metadata filter、query rewrite 等仍属于 Phase 6~7。

---

## 二、必须严格遵守的范围边界

### 2.1 本阶段必须完成

按照规格，Phase 5 必须完成：

1. 实现本地 `embedding_service`
2. 实现本地 `reranker` 服务封装
3. 实现 Qdrant upsert
4. 实现 PostgreSQL FTS keyword index
5. 实现 metadata payload
6. 支持 `is_active` filter
7. 入库任务完成后自动建立索引

### 2.2 本阶段不要提前实现

本阶段不要越界实现以下内容：

- 不要实现 `/api/v1/query/retrieve`
- 不要实现向量检索 search API
- 不要实现 PostgreSQL FTS 查询接口
- 不要实现 RRF 融合
- 不要实现 metadata filter builder
- 不要实现 query rewrite
- 不要实现 answer generation
- 不要实现 citation checker

### 2.3 本阶段只索引 child chunk

这是硬约束，必须从实现开始就严格遵守：

- **只索引 child chunk**
- parent chunk 仅用于后续上下文回填
- parent 不进入 Qdrant
- parent 不进入关键词索引主流程

如果把 parent 一起索引，会直接破坏后续检索与引用设计。

---

## 三、当前仓库现状与 Phase 5 的前置条件

### 3.1 当前已具备的基础

进入 Phase 5 前，理论上应已具备：

- Phase 0：工程、配置、基础设施联通
- Phase 1：数据库模型、Alembic、核心表
- Phase 2：上传与任务入口
- Phase 3：解析与清洗
- Phase 4：chunk 生成、`chunk_hash`、metadata、`chunks` 表持久化

### 3.2 Phase 5 的关键依赖

本阶段应依赖以下已有能力：

- `chunks` 表中已经有 parent / child 数据
- child chunk 已有 `normalized_text`
- child chunk 已有 `chunk_hash`
- `document_versions` / `documents` 元数据可回取
- `config.py` 已可扩展本地模型目录与 Qdrant 配置
- worker 任务流已能执行到 chunk 落库之后

如果 Phase 4 还没有稳定生成 child chunk，就不要直接进入 Phase 5。
因为本阶段的索引对象就是 child chunk。

---

## 四、Phase 5 的实施原则

### 4.1 embedding 与 reranker 都必须本地加载

根据既有约束：

- embedding：本地 Qwen Embedding，进程内直接加载
- reranker：本地 Qwen3 Reranker，进程内直接加载
- 不使用 OpenAI-compatible embedding proxy
- 不把 reranker 当作远程 API 服务

### 4.2 索引建立是“入库链路的一部分”，不是查询时懒构建

child chunk 的 embedding、Qdrant upsert、FTS 字段建立，应在 ingest 链路中完成。
不要等用户第一次查询时才去补索引。

### 4.3 metadata payload 必须统一、可过滤、可回溯

无论是 Qdrant payload，还是 PostgreSQL 中用于检索与回显的字段，都必须能支持后续：

- `doc_type`
- `doc_title`
- `version_status`
- `security_domain`
- `chapter / section / article_no`
- `page_start / page_end`
- `is_active`
- `parent_chunk_id`

### 4.4 本阶段只建立“索引能力”，不负责“召回编排”

也就是说，本阶段关注的是：

- 数据能不能索引进去
- 结构对不对
- 未来能不能按 `chunk_id` 找回来

而不是：

- 查询效果是否最优
- 多路检索如何融合
- 查询排序是否合理

这些属于后面阶段。

---

## 五、建议的实现拆分

建议把 Phase 5 拆成 7 个步骤执行。

---

## 六、Step 1：补齐模型与索引配置项

### 目标

让本地模型路径、Qdrant collection、向量维度与索引参数都通过配置可管理。

### 推荐文件

- `backend/app/config.py`
- `.env.example`

### 建议新增配置

至少应补充：

- `embedding_model_path`
- `reranker_model_path`
- `qdrant_collection_name`
- `embedding_vector_size`
- `qdrant_distance_metric`（第一版固定 `Cosine`，但配置层仍可显式化）
- `fts_language_config`（如需要）
- 可能的 batch size 配置

### 注意点

- 本地模型路径应指向项目根目录下的 `models/embedding/` 和 `models/reranker/`
- `models/` 已在 `.gitignore`，不要把模型文件纳入版本控制
- 配置项需要兼顾本地运行与 Docker 环境

---

## 七、Step 2：实现本地 embedding_service

### 目标

提供统一的本地向量生成接口。

### 推荐文件

- `backend/app/services/embedding_service.py`

### 最低要求

1. 从本地模型目录加载 embedding 模型
2. 提供单条与批量 embedding 能力
3. 输入使用 chunk 的 `normalized_text`
4. 输出固定维度向量
5. 模型加载失败时抛出明确错误

### 设计要求

- 模型实例应支持复用，避免每个 chunk 重新加载模型
- API 层与 worker 不直接接触底层模型调用细节
- 批处理能力优先在 service 层封装好

### 注意点

- embedding 输入对象是 **child chunk**，不是 parent chunk
- 不要在本阶段做查询向量化接口
- 不要把 embedding_service 做成通用 LLM service

---

## 八、Step 3：实现本地 reranker 服务封装

### 目标

为后续 Phase 6 提前准备真实 reranker 封装，但本阶段先完成加载与基本调用能力。

### 推荐文件

- `backend/app/services/reranker.py`

### 本阶段最低要求

1. 从本地模型目录加载 reranker
2. 定义统一接口，例如：
   - 输入 query + candidate texts
   - 输出 rerank scores
3. 验证模型可正常加载与基本推理

### 边界说明

- 本阶段不要求把 reranker 接进查询链路
- 只要求服务封装真实存在、可用、可测试

### 注意点

- 不要为了 Phase 5 提前实现完整检索融合
- 不要用假 reranker 占位替代真实模型封装，规格明确要求第一版接真实 reranker

---

## 九、Step 4：实现 Qdrant Vector Store

### 目标

把 child chunk 的 embedding 与 payload 写入 Qdrant。

### 推荐文件

- `backend/app/services/vector_store.py`
- 如有需要，辅助逻辑可放 `backend/app/services/index_service.py`

### 本阶段最低要求

1. 初始化 Qdrant collection
2. collection 使用 `Cosine` 距离
3. 为 child chunk 生成 point
4. point 中包含统一 payload
5. 支持 upsert
6. 支持按 `chunk_id` 回查或验证写入结果
7. 支持 `is_active` payload 字段

### 推荐 payload 字段

至少应包含：

- `chunk_id`
- `document_id`
- `version_id`
- `doc_type`
- `doc_title`
- `chapter`
- `section`
- `article_no`
- `page_start`
- `page_end`
- `security_domain`
- `version_status`
- `is_active`
- `chunk_type`
- `parent_chunk_id`

### 注意点

- point id 与 `chunk_id` 的映射要稳定
- 只 upsert child chunk
- parent chunk 不要混入 collection

---

## 十、Step 5：实现 PostgreSQL FTS keyword index

### 目标

让 child chunk 同时具备关键词检索基础。

### 推荐文件

- `backend/app/services/keyword_store.py`
- 如有需要，配合 `index_service.py`

### 本阶段最低要求

1. 只对 child chunk 建立关键词索引
2. 使用 `chunks.search_tsv` 字段
3. 在 chunk 写入或索引阶段更新 `search_tsv`
4. 保留原始字段，便于未来 FTS 与 fallback 检索
5. 支持 `is_active` 可见性约束

### 设计要求

- 虽然 Phase 6 才会真正做 FTS 查询，但 Phase 5 必须把字段更新机制打通
- 若中文分词方案暂不复杂化，也不要阻碍编号、英文术语、CVE、标准编号等检索基础

### 注意点

- 不要在本阶段急着实现复杂中文检索优化
- 不要引入 OpenSearch
- 不要把关键词索引设计成独立外部系统

---

## 十一、Step 6：实现 metadata payload 与 index_service 编排

### 目标

统一组装索引所需元数据，并串起 embedding + Qdrant + FTS 的建立流程。

### 推荐文件

- `backend/app/services/index_service.py`

### 建议职责

1. 从 chunk record 组装统一 metadata payload
2. 过滤出需要索引的 child chunk
3. 调用 embedding_service 生成向量
4. 调用 vector_store upsert 到 Qdrant
5. 调用 keyword_store 更新 `search_tsv`
6. 处理 `is_active` 与 `chunk_type` 规则

### 设计要求

- index_service 应作为“索引编排层”
- worker 不应直接分别拼接 Qdrant / FTS 逻辑
- payload 结构在这里统一最合适

### 关于 `is_active`

第一版必须支持：

- `chunks.is_active = true`
- Qdrant payload 中也保留 `is_active`
- 后续 delete / replace 时可据此控制可见性

---

## 十二、Step 7：接入 worker、测试与验收

### 目标

把 Phase 4 的 chunk 落库链路升级为“自动建索引链路”。

### 推荐文件

- `backend/app/workers/ingest_worker.py`
- `backend/tests/test_embedding_service.py`
- `backend/tests/test_vector_store.py`
- `backend/tests/test_keyword_store.py`
- `backend/tests/test_index_service.py`

### worker 在本阶段应做的事情

建议主流程：

1. 上传任务进入 `processing`
2. parser -> cleaner -> chunk_service
3. chunk 落库
4. 提取 child chunks
5. 调用 index_service 建立 embedding / Qdrant / FTS 索引
6. 全部成功后再更新任务状态

### 任务状态建议

到 Phase 5 为止，“完整入库链路”已经第一次具备比较完整的语义了。
因此若：

- 文件解析成功
- chunk 落库成功
- child chunk 索引成功

则可以较合理地把 `ingest_task.status` 标记为 `completed`。

### 至少要补的测试

#### 1. embedding_service 测试

建议覆盖：

- 模型能从本地目录加载
- 单条 embedding 成功
- 批量 embedding 成功
- 向量维度正确

#### 2. reranker 测试

建议覆盖：

- 模型能从本地目录加载
- 基础 rerank 调用成功
- 输出分数数量与输入候选一致

#### 3. vector_store 测试

建议覆盖：

- Qdrant collection 能初始化
- child chunk 能 upsert 成功
- 能根据 `chunk_id` 找回结果
- payload 字段完整
- `is_active` 写入正确

#### 4. keyword_store 测试

建议覆盖：

- `search_tsv` 能更新
- 只更新 child chunk
- `is_active` 状态正确保留

#### 5. index_service 测试

建议覆盖：

- 只索引 child chunk
- embedding / vector / keyword 三步调用顺序正确
- payload 组装正确

#### 6. worker 集成测试

建议覆盖：

- 上传后 child chunk 完成索引
- PostgreSQL 与 Qdrant 中都能看到结果
- 任务状态最终为 `completed`
- 失败时能写入错误信息

### 测试样例建议

建议使用：

- 一组已经过 Phase 4 切分的小样本文档
- 至少包含 parent + child chunk
- 最好含有法规编号、英文术语、CVE 或标准编号等内容，方便验证 payload 和关键词索引

### 验收命令建议

请优先在项目专用环境中运行 Python 相关命令。

如果使用 conda：

```bash
conda run -n rag_sec_phase1 pytest backend/tests/test_embedding_service.py
conda run -n rag_sec_phase1 pytest backend/tests/test_vector_store.py -m integration
conda run -n rag_sec_phase1 pytest backend/tests/test_keyword_store.py -m integration
conda run -n rag_sec_phase1 pytest backend/tests/test_index_service.py -m integration
```

如果使用 venv：

```bash
.venv\Scripts\python -m pytest backend/tests/test_embedding_service.py
.venv\Scripts\python -m pytest backend/tests/test_vector_store.py -m integration
.venv\Scripts\python -m pytest backend/tests/test_keyword_store.py -m integration
.venv\Scripts\python -m pytest backend/tests/test_index_service.py -m integration
```

### Phase 5 验收标准

必须达到：

- child chunk 能写入 PostgreSQL
- 向量能写入 Qdrant
- 关键词检索字段已建立
- 能根据 `chunk_id` 找回结果
- 本地 embedding 模型从项目 `models/` 目录加载
- 本地 reranker 模型从项目 `models/` 目录加载

---

## 十三、推荐文件改动清单

以下是执行 Phase 5 时大概率会涉及的文件。

### 需要新增或完善的文件

- `backend/app/services/embedding_service.py`
- `backend/app/services/reranker.py`
- `backend/app/services/vector_store.py`
- `backend/app/services/keyword_store.py`
- `backend/app/services/index_service.py`
- `backend/app/workers/ingest_worker.py`
- `backend/tests/test_embedding_service.py`
- `backend/tests/test_vector_store.py`
- `backend/tests/test_keyword_store.py`
- `backend/tests/test_index_service.py`

### 可能需要调整的现有文件

- `backend/app/config.py`
- `.env.example`
- `backend/app/services/chunk_service.py`
- `backend/app/utils/hash_utils.py`
- `backend/app/models/chunk.py`
- `backend/app/dependencies.py`
- `README.md`
- `pyproject.toml`
- `docker-compose.yml`

### 如需支持 worker 独立运行

可能还需要调整：

- Celery worker 启动配置
- compose 中的 worker 服务
- 本地模型目录挂载方式

---

## 十四、建议的实现顺序

推荐顺序如下：

1. 补齐 embedding / reranker / Qdrant / FTS 配置项
2. 实现 embedding_service
3. 实现 reranker 服务封装
4. 实现 vector_store
5. 实现 keyword_store
6. 实现 index_service
7. 接入 ingest worker
8. 准备测试数据与模型路径
9. 编写 embedding / vector / keyword / index / worker 测试
10. 更新 README 的 Phase 5 说明
11. 验收

---

## 十五、实现时最容易踩的坑

### 1. 把 parent chunk 也一起索引

这是最常见且最严重的边界错误之一。
规格已经明确：**只索引 child chunk**。

### 2. 模型加载方式不符合约定

如果把 embedding / reranker 做成远程 API 或兼容层代理，就偏离了既有默认决策。

### 3. payload 结构不统一

如果 Qdrant payload、数据库字段、后续检索过滤字段不一致，Phase 6 会非常痛苦。

### 4. `search_tsv` 字段只建表不更新

Phase 1 已有字段，不代表 Phase 5 自动完成了关键词索引逻辑。
必须把更新链路补齐。

### 5. `is_active` 只在数据库中有，没有进 payload

后续删除与版本切换时会依赖多端一致的可见性控制。

### 6. worker 里直接写死全部索引细节

worker 应调用 `index_service`，不要自己拼 embedding、Qdrant、FTS 三套逻辑。

### 7. 没有在项目专用环境中运行 Python 测试

当前用户偏好已经明确：

- 必须使用项目专用 conda / venv
- 不要污染全局 Python 环境

---

## 十六、建议给 Claude Code 的执行提示

如果后续要让 Claude Code 直接实现 Phase 5，提示词应强调：

- 当前仓库已完成 Phase 0、Phase 1，且 Phase 2~4 已具备上传、解析、切分与 chunk 落库基础
- 只实现 embedding、reranker、Qdrant、FTS、payload 与索引编排
- 不要提前实现检索接口、RRF、query rewrite、answer generation
- 只索引 child chunk
- 本地模型必须从项目 `models/` 目录加载
- 所有新增代码保留完整中文注释
- Python 相关命令必须在项目专用 conda / venv 环境中运行
- 输出必须包含：修改文件、运行命令、测试命令、验收方法

---

## 十七、最终结论

Phase 5 的本质是：

**把“数据库中的结构化 chunk 数据”，升级为“真正可被后续检索系统召回的索引数据”。**

完成本阶段后，系统将具备：

- 本地 embedding 能力
- 本地 reranker 封装能力
- Qdrant 向量索引
- PostgreSQL FTS 关键词索引
- 统一 metadata payload
- child chunk 自动建索引链路

这正是 Phase 6 进入基础检索接口与召回逻辑实现的前提。
