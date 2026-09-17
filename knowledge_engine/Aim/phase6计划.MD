# Phase 6 实施计划（基础检索）

> 本计划基于当前仓库 **Phase 0~5 已完成或将完成** 的前提编写。
> 
> 本阶段目标是：在不越过规格边界的前提下，完成 **Qdrant 向量检索、PostgreSQL FTS 检索、metadata filter、RRF 融合、`/api/v1/query/retrieve` 调试接口以及 top_k chunk 返回**。

---

## 一、Phase 6 的目标

根据权威规格，Phase 6 的唯一目标是：

**实现一个可用的基础检索接口，让系统第一次具备“输入问题 → 返回相关 chunks”的能力。**

这一阶段要解决的问题是：

- 如何做向量检索
- 如何做 PostgreSQL FTS 检索
- 如何按 metadata 过滤结果
- 如何把两路结果做 RRF 融合
- 如何通过调试接口返回检索明细
- 如何返回最终 top_k 相关 chunks

但 Phase 6 仍然**不是**完整问答阶段。
不会生成自然语言答案，也不会做 citation checker，这些属于后续 Phase 8。

---

## 二、必须严格遵守的范围边界

### 2.1 本阶段必须完成

按照规格，Phase 6 必须完成：

1. 实现 Qdrant vector search
2. 实现 PostgreSQL FTS search
3. 实现 metadata filter
4. 实现 RRF 融合
5. 实现 `/api/v1/query/retrieve`
6. 返回 top_k chunks

### 2.2 本阶段不要提前实现

本阶段不要越界实现以下内容：

- 不要实现完整 `query/answer`
- 不要实现 answer generation
- 不要实现 citation checker
- 不要实现 query rewrite 主链路
- 不要实现 safety_guard 主链路
- 不要实现 intent_classifier 主链路
- 不要实现 metadata_filter_builder 的智能推断
- 不要实现用户输入优化编排

### 2.3 本阶段检索对象仍然只限 child chunk

必须继续严格遵守：

- Qdrant 检索对象是 child chunk
- PostgreSQL FTS 检索对象是 child chunk
- parent chunk 不参与检索结果主集合
- parent 仅为后续 Phase 8 的上下文回填做准备

---

## 三、当前仓库现状与 Phase 6 的前置条件

### 3.1 当前已具备的基础

进入 Phase 6 前，理论上应已具备：

- Phase 4：child chunk 已生成并落库
- Phase 5：child chunk 已完成向量索引与关键词索引
- `search_tsv` 更新链路已打通
- Qdrant payload 已具备 metadata
- `is_active` 已进入数据库字段与 payload

### 3.2 Phase 6 的关键依赖

本阶段依赖：

- `embedding_service` 已可用（用于 query 向量化）
- `vector_store` 已支持 search
- `keyword_store` 已支持 FTS 查询
- `index_service` 与 metadata payload 结构已经统一
- `chunks` / `documents` / `document_versions` 状态字段可用于过滤

如果 Phase 5 还没有把索引层真正建起来，就不要直接进入 Phase 6。

---

## 四、Phase 6 的实施原则

### 4.1 先把召回链路打通，再谈检索优化

本阶段重点是：

- 能搜到
- 能按规则过滤
- 能融合
- 返回结构清晰

不要在此阶段提前做复杂优化，例如：

- 智能 query rewrite
- 高级召回分析
- 多阶段重排链路扩展

### 4.2 vector search 与 keyword search 必须并行存在

这是混合检索的核心：

- 向量检索负责语义召回
- FTS 负责关键词、编号、术语等精确召回

不能只做其中一路然后假装完成 Phase 6。

### 4.3 默认过滤规则必须从第一天就正确

默认检索作用域必须遵守既有约定：

- `documents.status = active`
- `document_versions.version_status = active`
- `chunks.is_active = true`
- `current_version_only = true`

如果默认过滤做错，后续版本管理与删除逻辑会全部失真。

### 4.4 `/query/retrieve` 是调试接口，不是最终用户答案接口

因此它应偏向返回：

- 原始检索结果
- 融合结果
- chunk 元信息
- score

而不是生成最终答案文本。

---

## 五、建议的实现拆分

建议把 Phase 6 拆成 6 个步骤执行。

---

## 六、Step 1：实现 query 向量化与 vector search

### 目标

让用户 query 能通过 embedding_service 转为向量，并在 Qdrant 中召回相关 child chunk。

### 推荐文件

- `backend/app/services/retriever.py`
- `backend/app/services/vector_store.py`

### 最低要求

1. 使用 embedding_service 对 query 向量化
2. 调用 vector_store.search
3. 支持 `top_k=30` 默认值
4. 支持 metadata filter 下推到 Qdrant
5. 返回统一的 `SearchResult` 结构

### 注意点

- query embedding 与文档 embedding 必须使用同一模型
- 只返回 child chunk
- 不要在这里加入 reranker 逻辑

---

## 七、Step 2：实现 PostgreSQL FTS search

### 目标

让 query 能通过 PostgreSQL `search_tsv` 字段做关键词检索。

### 推荐文件

- `backend/app/services/keyword_store.py`
- `backend/app/services/retriever.py`

### 最低要求

1. 基于 `search_tsv` 做 FTS 查询
2. 默认 `top_k=30`
3. 支持 metadata filter
4. 支持编号、英文术语、标准编号等基础召回
5. 如有中文召回不足，可保留 `ILIKE` fallback 入口，但不替代主流程

### 注意点

- 本阶段可以先把 FTS 主链路做好
- fallback 只作补充，不要取代 FTS
- 不要引入 OpenSearch

---

## 八、Step 3：实现 metadata filter

### 目标

让检索层支持基础结构化过滤。

### 推荐文件

- `backend/app/services/metadata_filter.py`
- 或在 `retriever.py` 中先实现基础过滤映射，再在 Phase 7 拆分智能构建逻辑

### 第一版必须支持的过滤字段

至少包括：

- `doc_type`
- `doc_title`
- `version_status`
- `security_domain`
- `chapter`
- `section`
- `article_no`
- `page_start`
- `page_end`
- `is_active`
- `current_version_only`

### 默认规则

- 多值 `doc_type`：OR
- 多值 `security_domain`：任一命中
- 默认启用 `is_active=true`
- 默认启用 `current_version_only=true`

### 注意点

- 本阶段只做“显式 filter 应用”
- 不做“从自然语言智能推断 filter”，那是 Phase 7 的事

---

## 九、Step 4：实现 RRF 融合

### 目标

把向量检索和关键词检索的结果融合成一个统一排序结果。

### 推荐文件

- `backend/app/services/fusion.py`

### 固定参数

按规格：

- vector search top_k = 30
- keyword search top_k = 30
- RRF `k = 60`

### 最低要求

1. 支持两路结果输入
2. 基于 `chunk_id` 融合
3. 输出统一排序结果
4. 保留原始 score / 来源，便于调试

### 注意点

- 本阶段只做 RRF，不要提前接 reranker
- reranker 虽然在 Phase 5 已封装，但正式进入检索链路属于后续更完整编排阶段

---

## 十、Step 5：实现 `/api/v1/query/retrieve` 调试接口

### 目标

提供一个可直接观察检索效果的 HTTP 接口。

### 推荐文件

- `backend/app/api/query.py`
- `backend/app/schemas/query.py`

### 请求建议

至少支持：

- `query`
- `top_k`
- `filters`
- 可选 debug 开关

### 返回建议

可以包含：

- 原始 query
- vector results
- keyword results
- fused results
- 最终返回 chunks

### 重要边界

- 这是检索调试接口，不是最终问答接口
- Route 层保持轻量，检索逻辑必须放服务层

---

## 十一、Step 6：测试与验收

### 目标

验证基础检索链路可用、可过滤、可融合。

### 建议新增测试文件

- `backend/tests/test_retriever.py`
- `backend/tests/test_fusion.py`
- `backend/tests/test_query_retrieve_api.py`

### 至少要覆盖的测试

#### 1. vector search

- query 向量化成功
- Qdrant 能返回结果
- 结果只包含 child chunk

#### 2. keyword search

- FTS 能返回关键词匹配结果
- 编号类内容可召回

#### 3. metadata filter

- `doc_type` 过滤有效
- `version_status` 过滤有效
- 默认 `is_active=true` 生效
- 默认 `current_version_only=true` 生效

#### 4. RRF

- 两路结果能正确融合
- 排序结果符合预期

#### 5. `/query/retrieve` API

- 返回结构正确
- 能返回 top_k chunks
- debug 明细存在

### 验收命令建议

如果使用 conda：

```bash
conda run -n rag_sec_phase1 pytest backend/tests/test_retriever.py -m integration
conda run -n rag_sec_phase1 pytest backend/tests/test_fusion.py
conda run -n rag_sec_phase1 pytest backend/tests/test_query_retrieve_api.py -m integration
```

如果使用 venv：

```bash
.venv\Scripts\python -m pytest backend/tests/test_retriever.py -m integration
.venv\Scripts\python -m pytest backend/tests/test_fusion.py
.venv\Scripts\python -m pytest backend/tests/test_query_retrieve_api.py -m integration
```

### Phase 6 验收标准

必须达到：

- `/api/v1/query/retrieve` 可以返回相关 chunks
- 支持 `doc_type` filter
- 支持 `version_status` filter
- 支持 `is_active=true` 默认过滤
- 支持 `current_version_only=true` 默认过滤

---

## 十二、推荐文件改动清单

### 需要新增或完善的文件

- `backend/app/services/retriever.py`
- `backend/app/services/fusion.py`
- `backend/app/services/metadata_filter.py`
- `backend/app/api/query.py`
- `backend/app/schemas/query.py`
- `backend/tests/test_retriever.py`
- `backend/tests/test_fusion.py`
- `backend/tests/test_query_retrieve_api.py`

### 可能需要调整的现有文件

- `backend/app/services/vector_store.py`
- `backend/app/services/keyword_store.py`
- `backend/app/services/embedding_service.py`
- `backend/app/api/__init__.py`
- `backend/app/config.py`
- `README.md`

---

## 十三、建议的实现顺序

1. 补 retriever 所需的统一结果结构
2. 打通 vector search
3. 打通 FTS search
4. 实现 metadata filter
5. 实现 RRF 融合
6. 暴露 `/query/retrieve`
7. 编写测试
8. 更新 README
9. 验收

---

## 十四、实现时最容易踩的坑

### 1. 把 parent chunk 当成召回结果

这是边界错误，必须避免。

### 2. 过滤规则只在一侧生效

如果只在 Qdrant 生效、不在 FTS 生效，融合结果会失真。

### 3. 默认 current version 过滤没做好

这会导致历史版本被混入默认结果。

### 4. 把 reranker 提前塞进主链路

会越过当前阶段边界。

---

## 十五、最终结论

Phase 6 的本质是：

**把“已经被索引的 child chunk”，升级为“可以被统一查询和返回的检索结果”。**

完成本阶段后，系统将第一次具备真正可用的检索能力，这正是 Phase 7 做用户输入优化、Phase 8 做答案生成的前提。
