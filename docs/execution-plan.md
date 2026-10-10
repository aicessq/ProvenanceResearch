# 下一阶段迭代计划（P3-P5 重排版）

状态：2026-10-10 由用户批准并落盘，作为下一轮迭代的执行任务说明。
执行规则：**每完成一小部分即提交一次 git**（用户 2026-10-10 要求），提交前对应测试必须通过。
与 [roadmap.md](roadmap.md) 的关系：本文件定义**执行顺序**与各阶段输入/任务/验收；[roadmap.md](roadmap.md) 仍是阶段验收细则的权威来源。两者如有冲突，先修文档再动手。

> **执行顺序裁决（2026-10-10）**：本文"执行优先级总结"与结尾段落均把 P5 Demo UI 放在 P3b OCR/Vision 之前（"完成前半段（到 P4/P5 第一版）……后面的 OCR/Vision/硬化"），但正文 Phase 5/6 的编号顺序相反。按总结与结尾段落取 **P5 先于 P3b**；如需相反顺序请指出。

## 0. 总体目标

将当前 ProvenanceResearch 从：

> 两个旧系统的工程基线：
>
> * Knowledge Engine（固定流水线 RAG）
> * Deep Research System（固定拓扑多 Agent）

演进为：

> 可演示、可评测、可扩展的 Evidence-grounded Agentic RAG 系统。

最终交付能力：

1. 用户提出研究问题；
2. Agent 根据证据缺口自主决定是否追加检索；
3. 支持私有知识库、Web 搜索、arXiv 学术来源；
4. 所有回答事实都有 provenance citation；
5. 无充分证据时拒答；
6. SSE 实时展示 Agent 执行过程；
7. 前端展示对话、证据、任务状态；
8. 支持评测：retrieval、citation accuracy、refusal accuracy、agent improvement。

## 总执行原则

### 原则 1：先完成 Vertical Slice，再扩展能力

禁止先实现所有 provider、OCR、vision、复杂 UI，再尝试跑完整流程。必须优先完成这条完整闭环：

```
Question → Agent → Tool → Evidence → Reader → Citation Gate → Answer / Refusal
```

### 原则 2：所有阶段必须保持可运行状态

每阶段完成后必须：单元测试通过；CI 通过；docs 更新；decisions.md 追加记录；不允许破坏已有 KE/DRS 测试基线。

### 原则 3：小步提交

每完成一小部分即提交一次 git（2026-10-10 用户要求）；每部分独立可运行、测试通过。

## Phase 0：安全与基础修复（P2.5）

目标：消除公开仓库中最影响可信度的问题。

### 0.1 修复 DRS 模型测试接口

问题：当前 `POST /models/test` 可能接受任意 api_base 出站。

修改：增加 allowlist provider；禁止任意 URL；SSRF 防护。

验收：测试 localhost、私网 IP、file://、非允许 provider 全部拒绝。

### 0.2 删除 fake success 行为

禁止：

* Tavily 失败 `return mock result`；
* LLM 失败 `return local extraction answer`。

统一返回 `ProviderUnavailableError`，由上层决定 retry / fallback / refusal。

### 0.3 修复 key routing

禁止跨 provider 找任意 key。改成 `provider → capability → key pool` 严格绑定。

## Phase 1：P3a-Core 云模型 Adapter

目标：建立未来所有 AI 能力统一接口。暂时不要实现所有 provider——只实现一个真实 provider 与一个 fake provider。

设计：新增 `providers/`（`llm/`、`embedding/`、`reranker/`、`ocr/`、`vision/`）。统一接口例如：

```python
class LLMProvider:
    async def generate(self, messages, metadata):
        ...
```

### LLM Adapter

支持 timeout、retry、429 handling、5xx retry、error classification。错误分类：

```
CONFIG_MISSING / AUTH_FAILED / RATE_LIMIT / SERVER_ERROR / TIMEOUT / INVALID_RESPONSE
```

### Embedding Adapter

必须记录 `provider / model / dimension / preprocess_version`，建立 `EmbeddingIdentity`；禁止不同 identity 使用同 collection。

### 验收

fake provider 模拟 401、429、timeout、malformed response，全部通过。

## Phase 2：P3c-text Tool Layer

目标：先完成文本世界 Agent 能力，**不要等待 OCR**。

新增工具：`kb_search`、`web_search`、`arxiv_search`、`source_fetch`、`evidence_read`。

### Source Registry

统一来源登记：

```python
class Source:
    id: str
    type: str
    url: str
    hash: str
    version: str
    metadata: dict
```

### Evidence Schema v2

核心对象：`Evidence`（`source_id`、`source_type`、`modality`、`content`、`locator`、`citation_id`）。locator 支持 `page / chunk / url / section`；bbox 暂留字段，不阻塞文本链路。

### 验收

给定问题可以得到 `Question → Evidence[] → Reader input`；所有 Evidence 都有 source identity 与 citation id。

## Phase 3：P3d Agentic RAG Core

目标：第一次形成完整 Demo。

### Agent Loop

有限循环，默认 `max_round=3`、`max_tool_calls=12`、`max_tokens=20000`、`deadline=180s`。

状态：`PLAN → TOOL_CALL → EVIDENCE_UPDATE → GAP_CHECK → GENERATE → VERIFY → DONE`。

### Gap Detection

不让 Agent 无限搜索。明确停止原因：`sufficient_evidence / budget_exhausted / deadline_exceeded / no_progress / citation_gate_failed`。

### Reader

固定 RRF baseline：KB top20、External top10，输出 top8 Evidence。

### Citation Gate v1

不要直接验证自然语言。LLM 先输出结构化 claims：

```json
[
  {
    "claim": "xxx",
    "citations": ["K123"]
  }
]
```

验证：citation 存在；citation scope 正确；数字/专名存在；semantic support。失败则拒答。

### SSE v1

Redis Stream，只负责 event replay（不负责 Agent crash recovery）。事件：`meta / plan / tool_call / tool_result / evidence / token_delta / citation / done / error`。

## Phase 4：P4 Evaluation

提前启动，不等全部完成。

### 建立 baseline

必须比较：**A** KB only；**B** Fixed mixed retrieval；**C** Agentic。

### 指标

实现 Recall@k、MRR、Citation accuracy、Citation coverage、Refusal accuracy、Latency、Cost。

### 第一轮

不用完整 56 题，先 15–20 个代表问题，覆盖 KB、web、paper、multi-step、impossible question。

## Phase 5：P5 Unified Frontend

目标：作品集 Demo。

### 页面

三栏：Conversation ｜ Evidence ｜ Task Timeline。

显示 Agent 当前计划、工具调用、搜索来源、citation。Evidence 点击展示原文、页面、来源。

（与正文原 Phase 5/6 编号的顺序差异见文首裁决：P5 在 P3b 之前执行。）

## Phase 6：P3b Multimodal Ingestion

现在进入 OCR/Vision。

### PDF pipeline

```
PDF → native extraction → OCR fallback → vision fallback → Evidence
```

支持 page、bbox、rotation normalized coordinates、asset hash。失败页面不能发布新版本。

测试：扫描 PDF 的 OCR success、OCR fail、partial fail。

## Phase 7：Production Hardening

最终收尾：

* Authentication：恢复 JWT；
* Rate limit：API 的 query、ingest；
* Observability：structured logs、metrics；
* Deployment：Docker Compose 最终形态 `postgres / redis / qdrant / backend / worker / frontend`。

## 最终验收标准

### Demo

用户输入"比较 A 和 B 技术路线，并说明哪个更适合某场景"，系统应：KB 搜索 → 发现不足 → Web/arXiv 补充 → Agent 停止 → Reader 合并 → Citation Gate 验证 → 输出带引用答案。

### 必须展示三个失败案例

1. 没有证据：输出拒答；
2. 来源冲突：展示多个 Evidence；
3. provider failure：展示错误处理。

## 最终 Portfolio 描述

完成后 README 改为：

> Built an evidence-grounded Agentic RAG research system that autonomously expands retrieval across private knowledge bases, web sources and academic papers under explicit budget constraints. Every factual claim is verified against registered provenance evidence, with reproducible evaluation against non-agentic baselines.

## 执行优先级总结

```
P2.5 Security fixes
        ↓
P3a Core Adapter
        ↓
P3c Text Tools
        ↓
P3d Agent + Citation + SSE
        ↓
P4 Evaluation
        ↓
P5 Demo UI
        ↓
P3b OCR/Vision
        ↓
Hardening
```

核心变化：**从"先造完整平台"改成"先造一个不可质疑的研究 Agent"**。完成前半段（到 P4/P5 第一版）后，这个项目就已经足够作为高级 AI Engineer 作品展示；后面的 OCR/Vision/硬化属于把它从优秀作品提升到接近生产系统。
