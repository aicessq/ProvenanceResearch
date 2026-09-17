# Phase 7 实施计划（用户输入优化）

> 本计划基于当前仓库 **Phase 0~6 已完成或将完成** 的前提编写。
> 
> 本阶段目标是：在不越过规格边界的前提下，完成 **safety_guard、intent_classifier、term_expander、query_rewriter、metadata_filter_builder 以及 `/query/rewrite` 调试接口**。

---

## 一、Phase 7 的目标

根据权威规格，Phase 7 的唯一目标是：

**让检索从“能搜”升级到“更懂用户在问什么、该搜什么、该拒绝什么”。**

这一阶段要解决的问题是：

- 如何识别攻击性或违规请求
- 如何判断问题意图
- 如何做安全领域术语扩展
- 如何把用户原始问题改写为更适合检索的 query
- 如何构建更精准的 metadata filter
- 如何通过调试接口观察改写与过滤结果

但 Phase 7 仍然**不是**最终答案阶段。
不会返回完整最终答案，也不会做 citation grounding，这些属于 Phase 8。

---

## 二、必须严格遵守的范围边界

### 2.1 本阶段必须完成

按照规格，Phase 7 必须完成：

1. 实现 `safety_guard`
2. 实现 `intent_classifier`
3. 实现 `term_expander`
4. 实现 `query_rewriter`
5. 实现 `metadata_filter_builder`
6. 实现 `/query/rewrite` 调试接口

### 2.2 本阶段不要提前实现

本阶段不要越界实现以下内容：

- 不要实现完整 `/query/answer`
- 不要实现 answer generation
- 不要实现 citation checker
- 不要实现最终问答编排
- 不要实现评测运行逻辑

### 2.3 safety_guard 是检索链路第一步

这一点必须从设计上就落实：

- 先判定是否允许继续
- 拒绝/重定向请求也要被记录
- 不要把安全判断推迟到答案生成之后

---

## 三、当前仓库现状与 Phase 7 的前置条件

### 3.1 当前已具备的基础

进入 Phase 7 前，理论上应已具备：

- Phase 6：基础检索接口已可用
- Phase 5：embedding / reranker / 索引层已具备
- `query_logs` 表已存在
- `retriever.py` 已可接收 query 与 filters

### 3.2 Phase 7 的关键依赖

本阶段应依赖：

- `llm_service.py` 作为远程大模型调用封装入口
- 本地术语词典或规则表
- 已存在的 metadata filter 结构
- 基础检索调试接口或服务层能力

如果 Phase 6 还没有基础检索能力，Phase 7 的优化将无法形成实际收益。

---

## 四、Phase 7 的实施原则

### 4.1 规则优先，LLM 作为补充

尤其是 safety_guard：

- 先规则匹配
- 规则不明确再走 LLM 分类

这样能提高可控性，降低不必要的模型调用成本。

### 4.2 各模块职责分离

- `safety_guard`：判定是否允许继续
- `intent_classifier`：识别问题类别
- `term_expander`：补充同义词、缩写、标准名称
- `query_rewriter`：生成适合检索的 rewritten query
- `metadata_filter_builder`：把显式/隐式条件转换成结构化 filters

不要把这些能力混成一个大函数。

### 4.3 `/query/rewrite` 是调试接口，不是最终检索接口

因此它重点返回：

- intent
- 风险分类
- 扩展词
- 改写结果
- filters

而不是直接返回最终答案。

### 4.4 明确拒绝与重定向策略

对攻击性请求：

- 不能提供真实攻击步骤
- 可以转为防御、修复、检测、日志排查建议
- 必须返回结构化结果

---

## 五、建议的实现拆分

建议把 Phase 7 拆成 6 个步骤执行。

---

## 六、Step 1：实现 safety_guard

### 目标

识别攻击性请求，并决定 `allow / refuse / redirect`。

### 推荐文件

- `backend/app/services/safety_guard.py`
- `backend/app/prompts/safety_guard.md`

### 输出结构必须固定为

```json
{
  "action": "allow | refuse | redirect",
  "risk_type": "attack_request | bypass_request | malware_request | credential_theft | destructive_request | unknown",
  "reason": "string",
  "safe_response": "string"
}
```

### 最低要求

1. 支持规则匹配主路径
2. 模糊情况可调用 LLM
3. 输出结构固定
4. 拒绝/重定向可供 query_log 记录

---

## 七、Step 2：实现 intent_classifier

### 目标

识别问题属于法规、标准、教材、漏洞修复、总结、越界请求等哪一类。

### 推荐文件

- `backend/app/services/intent_classifier.py`
- `backend/app/prompts/intent_classifier.md`

### 分类至少包括

- `law_query`
- `standard_query`
- `textbook_query`
- `concept_explanation`
- `vulnerability_fix`
- `comparison`
- `summary`
- `attack_request`
- `out_of_scope`

### 输出建议

至少返回：

- `intent`
- `confidence`
- `reason`
- `suggested_doc_types`

---

## 八、Step 3：实现 term_expander

### 目标

把网络安全领域简称、缩写、术语映射成更适合召回的扩展词集合。

### 推荐文件

- `backend/app/services/term_expander.py`

### 最低要求

1. 维护本地术语词典
2. 支持缩写到全称扩展
3. 支持中英文术语扩展
4. 输出去重后的扩展词集合

### 示例方向

- `等保` -> `网络安全等级保护` / `GB/T 22239`
- `SQL注入` -> `SQL Injection` / `SQLi`
- `CII` -> `关键信息基础设施`

---

## 九、Step 4：实现 query_rewriter

### 目标

把用户自然语言问题改写成更适合检索的查询表达。

### 推荐文件

- `backend/app/services/query_rewriter.py`
- `backend/app/prompts/query_rewriter.md`

### 输出建议

至少包含：

- `rewritten_query`
- `search_keywords`
- `sub_queries`

### 设计要求

- rewritten_query 要更明确、更完整
- 不能改变用户问题本意
- 不要凭空增加不存在的法规或标准编号

---

## 十、Step 5：实现 metadata_filter_builder

### 目标

根据用户显式条件、intent 和术语信息，构建结构化 filter。

### 推荐文件

- `backend/app/services/metadata_filter.py`

### 输出建议

至少支持：

- `doc_type`
- `version_status`
- `security_domain`
- `is_active`
- `current_version_only`

### 设计要求

- 用户显式 filter 优先级最高
- 系统推断 filter 只能补充，不能覆盖用户明确输入
- 默认保留 active/current version 约束

---

## 十一、Step 6：实现 `/query/rewrite` 调试接口与测试

### 目标

提供可视化调试入口，并验证优化链路的结构化输出。

### 推荐文件

- `backend/app/api/query.py`
- `backend/app/schemas/query.py`
- `backend/tests/test_safety_guard.py`
- `backend/tests/test_query_rewriter.py`
- `backend/tests/test_intent_classifier.py`
- `backend/tests/test_query_rewrite_api.py`

### 至少要覆盖的测试

#### 1. safety_guard

- 明确攻击请求被识别为 `attack_request`
- 合规问题正常 `allow`
- 输出结构完整

#### 2. intent_classifier

- “等保三级日志要留多久” -> `standard_query`
- “SQL注入教材里怎么讲” -> `textbook_query`
- “绕过WAF payload” -> `attack_request`

#### 3. term_expander

- 缩写扩展正确
- 中英文扩展有效
- 去重逻辑正确

#### 4. query_rewriter

- 能输出 rewritten_query
- 能输出 search_keywords 和 sub_queries
- 不篡改原始语义

#### 5. metadata_filter_builder

- 默认 active/current version 约束生效
- 用户显式 filter 优先生效

#### 6. `/query/rewrite` API

- 返回结构正确
- 包含 safety / intent / rewrite / filter 结果

### 验收命令建议

如果使用 conda：

```bash
conda run -n rag_sec_phase1 pytest backend/tests/test_safety_guard.py
conda run -n rag_sec_phase1 pytest backend/tests/test_query_rewriter.py
conda run -n rag_sec_phase1 pytest backend/tests/test_query_rewrite_api.py -m integration
```

如果使用 venv：

```bash
.venv\Scripts\python -m pytest backend/tests/test_safety_guard.py
.venv\Scripts\python -m pytest backend/tests/test_query_rewriter.py
.venv\Scripts\python -m pytest backend/tests/test_query_rewrite_api.py -m integration
```

### Phase 7 验收标准

必须达到：

- “等保三级日志要留多久”能识别为 `standard_query`
- “SQL注入教材里怎么讲”能识别为 `textbook_query`
- “绕过WAF payload”能识别为 `attack_request`
- 能输出 `rewritten_query` 和 `metadata filter`

---

## 十二、推荐文件改动清单

### 需要新增或完善的文件

- `backend/app/services/safety_guard.py`
- `backend/app/services/intent_classifier.py`
- `backend/app/services/term_expander.py`
- `backend/app/services/query_rewriter.py`
- `backend/app/services/metadata_filter.py`
- `backend/app/prompts/safety_guard.md`
- `backend/app/prompts/intent_classifier.md`
- `backend/app/prompts/query_rewriter.md`
- `backend/app/api/query.py`
- `backend/app/schemas/query.py`
- `backend/tests/test_safety_guard.py`
- `backend/tests/test_intent_classifier.py`
- `backend/tests/test_query_rewriter.py`
- `backend/tests/test_query_rewrite_api.py`

### 可能需要调整的现有文件

- `backend/app/services/retriever.py`
- `backend/app/services/llm_service.py`
- `backend/app/api/__init__.py`
- `backend/app/config.py`
- `README.md`

---

## 十三、建议的实现顺序

1. 实现 safety_guard
2. 实现 intent_classifier
3. 实现 term_expander
4. 实现 query_rewriter
5. 实现 metadata_filter_builder
6. 暴露 `/query/rewrite`
7. 编写测试
8. 更新 README
9. 验收

---

## 十四、实现时最容易踩的坑

### 1. 把安全判断放到最后

这样会让危险请求先穿过检索链路，违背设计初衷。

### 2. query_rewriter 过度发挥

改写应增强检索，不应改变问题本意。

### 3. filter builder 覆盖用户显式条件

这是典型的业务错误，必须避免。

### 4. 把 `/query/rewrite` 做成检索接口

它只负责展示输入优化结果，不负责完整检索与答案。

---

## 十五、最终结论

Phase 7 的本质是：

**把“能检索”的系统，升级为“更懂用户意图、更安全、更会检索准备”的系统。**

完成本阶段后，系统将具备面向安全领域的输入理解与改写能力，这正是 Phase 8 进入答案生成与引用校验的前提。
