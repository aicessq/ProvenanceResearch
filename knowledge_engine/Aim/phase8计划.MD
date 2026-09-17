# Phase 8 实施计划（答案生成与引用校验）

> 本计划基于当前仓库 **Phase 0~7 已完成或将完成** 的前提编写。
> 
> 本阶段目标是：在不越过规格边界的前提下，完成 **answer_generator、citation_checker、`/query/answer`、query_log 保存以及 parent context 回取**。

---

## 一、Phase 8 的目标

根据权威规格，Phase 8 的唯一目标是：

**让系统从“能返回相关 chunks”，升级为“能基于证据返回可读答案与引用”。**

这一阶段要解决的问题是：

- 如何把检索结果组织成可供 LLM 使用的上下文
- 如何回取 parent chunk 作为更完整的参考材料
- 如何生成结构化答案与 citations
- 如何检查答案是否被证据支持
- 如何在证据不足时避免编造
- 如何保存 query_log

---

## 二、必须严格遵守的范围边界

### 2.1 本阶段必须完成

按照规格，Phase 8 必须完成：

1. 实现 `answer_generator`
2. 实现 `citation_checker`
3. 实现 `/query/answer`
4. 保存 `query_log`
5. 回取 parent context

### 2.2 本阶段不要提前实现

本阶段不要越界实现以下内容：

- 不要实现 replace / chunk diff
- 不要实现完整评测体系
- 不要实现自动知识更新
- 不要实现复杂反馈闭环优化

### 2.3 必须严格基于证据回答

这是本阶段最重要的约束之一：

- 只基于检索到的材料回答
- 证据不足时必须明确说不足
- 不能编造法规条款号、章节号、页码、来源文件

---

## 三、当前仓库现状与 Phase 8 的前置条件

### 3.1 当前已具备的基础

进入 Phase 8 前，理论上应已具备：

- Phase 6：基础检索链路
- Phase 7：safety_guard、intent、rewrite、filter 构建
- Phase 4：parent-child chunk 结构
- Phase 5：索引层可用
- `query_logs` 表已存在

### 3.2 Phase 8 的关键依赖

本阶段应依赖：

- `retriever.py` 已能返回 top_k child chunks
- `parent_chunk_id` 已正确建立
- `llm_service.py` 已具备远程大模型调用封装
- `query_logs` 的写入能力可用

如果 Phase 6 和 Phase 7 还没打通，本阶段无法形成完整问答闭环。

---

## 四、Phase 8 的实施原则

### 4.1 检索与生成分层明确

- 检索层负责召回证据
- 生成层负责组织答案
- citation_checker 负责兜底校验

不要把所有逻辑塞进一个大函数。

### 4.2 parent context 是答案生成的重要上下文层

child chunk 用于检索，parent chunk 用于补足上下文。
因此本阶段要把这层关系真正用起来。

### 4.3 citation_checker 不是可选项

answer_generator 的输出不能直接裸返回。
必须经过 citation_checker 检查：

- 关键结论是否有依据
- 引用是否真实存在
- 页码与条款号是否来自 metadata

### 4.4 query_log 从这一阶段开始具备真实业务价值

应记录：

- 原始 query
- 改写 query
- intent
- filters
- retrieved chunk ids
- reranked/final chunk ids
- answer
- answer status
- latency
- model_name

---

## 五、建议的实现拆分

建议把 Phase 8 拆成 6 个步骤执行。

---

## 六、Step 1：实现 parent context 回取

### 目标

把检索命中的 child chunk 补全为更适合答案生成的上下文。

### 推荐文件

- `backend/app/services/retriever.py`
- 或新增辅助逻辑到 `answer_generator.py`

### 最低要求

1. 检索结果保留 `parent_chunk_id`
2. 能通过 `parent_chunk_id` 回取 parent chunk
3. 若没有 parent，则允许 fallback 使用 child 本身
4. 构造面向生成的 evidence context

---

## 七、Step 2：实现 answer_generator

### 目标

基于 evidence context 调用 LLM 生成结构化答案。

### 推荐文件

- `backend/app/services/answer_generator.py`
- `backend/app/prompts/answer_generator.md`

### 输出建议

至少包含：

- `answer`
- `citations`
- `confidence`
- `evidence_status`

### 设计要求

- Prompt 必须强调只基于参考资料回答
- 无明确依据时必须输出“当前知识库未检索到明确依据”
- 回答中应包含来源与页码信息

---

## 八、Step 3：实现 citation_checker

### 目标

检查答案是否被检索证据支持，并修正明显越界内容。

### 推荐文件

- `backend/app/services/citation_checker.py`
- `backend/app/prompts/citation_checker.md`

### 最低要求

1. 检查关键结论是否有证据支撑
2. 检查引用 chunk 是否存在
3. 检查页码 / 章节 / 条款号是否来自 metadata
4. 证据不足时改写答案或标记不足

### 输出建议

至少包含：

- `passed`
- `unsupported_claims`
- `fixed_answer`

---

## 九、Step 4：实现 `/query/answer`

### 目标

暴露完整问答接口。

### 推荐文件

- `backend/app/api/query.py`
- `backend/app/schemas/query.py`

### 主流程建议

1. safety_guard
2. intent + rewrite + filter
3. retriever
4. parent context 回取
5. answer_generator
6. citation_checker
7. 保存 query_log
8. 返回 answer + citations

### 返回结构建议

至少包含：

- `query`
- `intent`
- `rewritten_query`
- `answer`
- `citations`
- `retrieved_chunks`

---

## 十、Step 5：保存 query_log

### 目标

把一次完整问答过程中的核心信息记录下来。

### 推荐文件

- `backend/app/services/crud_service.py`
- 或新增 `query_log_service.py`

### 至少记录

- `user_query`
- `rewritten_query`
- `intent`
- `safety_action`
- `filters`
- `retrieved_chunk_ids`
- `reranked_chunk_ids`（如果当前链路已用）
- `answer`
- `answer_status`
- `latency_ms`
- `model_name`

---

## 十一、Step 6：测试与验收

### 建议新增测试文件

- `backend/tests/test_answer_generator.py`
- `backend/tests/test_citation_checker.py`
- `backend/tests/test_query_answer_api.py`

### 至少要覆盖的测试

#### 1. answer_generator

- 能生成结构化输出
- 证据不足时输出保守回答

#### 2. citation_checker

- 能识别 unsupported claims
- 能修正错误引用或不足结论

#### 3. `/query/answer` API

- 返回结构完整
- 含 citations
- 含页码
- 尽量含章节/条款号

#### 4. query_log

- 问答后数据库中存在 query_log 记录
- 关键字段被正确写入

### 验收命令建议

如果使用 conda：

```bash
conda run -n rag_sec_phase1 pytest backend/tests/test_answer_generator.py
conda run -n rag_sec_phase1 pytest backend/tests/test_citation_checker.py
conda run -n rag_sec_phase1 pytest backend/tests/test_query_answer_api.py -m integration
```

如果使用 venv：

```bash
.venv\Scripts\python -m pytest backend/tests/test_answer_generator.py
.venv\Scripts\python -m pytest backend/tests/test_citation_checker.py
.venv\Scripts\python -m pytest backend/tests/test_query_answer_api.py -m integration
```

### Phase 8 验收标准

必须达到：

- 用户提问后能返回答案
- 答案包含来源文件
- 答案包含页码
- 答案尽量包含章节/条款号
- 证据不足时不编造

---

## 十二、推荐文件改动清单

### 需要新增或完善的文件

- `backend/app/services/answer_generator.py`
- `backend/app/services/citation_checker.py`
- `backend/app/prompts/answer_generator.md`
- `backend/app/prompts/citation_checker.md`
- `backend/app/api/query.py`
- `backend/app/schemas/query.py`
- `backend/tests/test_answer_generator.py`
- `backend/tests/test_citation_checker.py`
- `backend/tests/test_query_answer_api.py`

### 可能需要调整的现有文件

- `backend/app/services/retriever.py`
- `backend/app/services/query_rewriter.py`
- `backend/app/services/llm_service.py`
- `backend/app/services/crud_service.py`
- `README.md`

---

## 十三、建议的实现顺序

1. 实现 parent context 回取
2. 实现 answer_generator
3. 实现 citation_checker
4. 打通 `/query/answer`
5. 接入 query_log
6. 编写测试
7. 更新 README
8. 验收

---

## 十四、实现时最容易踩的坑

### 1. 不做 citation_checker 就直接返回答案

这会让系统更容易幻觉。

### 2. 用 child 原文直接拼答案上下文，忽略 parent

会降低上下文完整性。

### 3. 编造章节或条款号

这是高风险错误，必须严格避免。

### 4. query_log 只记录 query，不记录结果链路

会削弱后续分析与评测能力。

---

## 十五、最终结论

Phase 8 的本质是：

**把“能返回相关 chunks”的系统，升级为“能基于证据输出答案与引用”的系统。**

完成本阶段后，系统第一次具备真正可用的 RAG 问答能力。
