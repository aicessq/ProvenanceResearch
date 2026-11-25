# Provenance Research

[![CI](https://github.com/aicessq/ProvenanceResearch/actions/workflows/ci.yml/badge.svg)](https://github.com/aicessq/ProvenanceResearch/actions/workflows/ci.yml)

> Evidence-grounded Agentic RAG for private knowledge bases, web sources and academic papers. A shared research graph scopes questions, explores within budget, and verifies claims before publication.

私库、网络与学术来源的 **证据可溯源 Agentic RAG** 研究系统。Agent 在共享的轮次、工具、token 和时限预算内检索与阅读原文。事实性断言经引用闸门核验后才能发布。部分有据时交付已核验内容并列出缺口。回答状态（`answered` / `refused`）与任务生命周期（`completed` / `failed` / `cancelled`）分开。

## 当前 Agent Loop

`/api/v1/tasks` 与兼容报告 API `/api/research` 共用一张 LangGraph。流程为 **定界 → 探索 → 草拟 → 核验 → 发布**。定界明确子问题与交付物，探索根据工具结果继续规划。核验发现断言待修或现有证据尚未组织成交付物时回到草拟，发现缺证且还有探索额度时回到原探索会话。

2026-11-25 版本支持证据 ID 回读、补查材料回填、现行法规版本核验，以及用已核验断言编排报告。交付物覆盖检查会区分缺证和待综合的内容，并可凭可定位的相反依据撤回冲突断言。流程图、变更细节与评测状态见 [实现走读](docs/walkthrough.md)。

## 系统组成

| 目录 | 职责 |
| --- | --- |
| `providers/` | 云模型适配层：LLM/OCR/vision（一真一假）、错误六分类、EmbeddingIdentity |
| `evidence/` + `tools/` | 统一 Evidence v2（来源身份/版本/范围）、五工具执行器（白名单+SSRF 防护） |
| `agent/` | 共享预算、Reader RRF、引用闸门、评测使用的旧 AgentLoop |
| `ingest/` | PDF/图像入库：native → OCR → vision 逐页回退，bbox/hash/图注关联到 citation |
| `eval/` | P4 冻结评测：A KB-only / B 固定混合 / C Agentic 对照 + 指标 + 安全样例 |
| `researcher/deep_research_system/` | 生产研究图、`/api/v1` 与兼容报告 API、SSE 和云配置 |
| `frontend/` | 统一三栏界面：Conversation ｜ Evidence ｜ Task Timeline + 云服务设置 |
| `knowledge_engine/` | 资产管理与 KB 检索子系统（迁移中；Celery ingest worker） |

## 快速开始

```bash
cp .env.example .env
# 1) 填云凭证（LLM_*/TAVILY_API_KEY 等；缺配置时任务显式失败，不降级本地/模拟模型）
# 2) 对外开放前设置 AUTH_ENABLED=true + AUTH_SECRET_KEY(≥32) + AUTH_BOOTSTRAP_USER/PASSWORD
docker compose up -d        # postgres + redis + qdrant + backend + worker + frontend
# 前端 http://localhost:8080 · API http://localhost:8000/docs
```

开发模式：`uvicorn main:app`（researcher/deep_research_system，127.0.0.1 默认仅本机）+ `cd frontend && npm run dev`。
前端联调冒烟：`python3 scripts/ui_smoke_server.py`（FAKE 运行时，仅测试，产出不是评测结论）。

## 三个失败案例（演示必看）

1. **无证据拒答**——例如询问「IETF 计划何时发布 TLS 1.4？」。若找不到可发布的依据，`answer.status=refused`，任务仍为 `completed`，时间线可见停止原因。
2. **来源冲突**——提问 2016 与 2025 版《网络安全法》条款对照（如"修改决定列为第几条"）：证据面板并列展示两个版本的原文页（`zh_cybersec_amend_2025` 与重新公布版），答案只引用各自版本的 citation，不同版本不误并。
3. **provider failure**——断开 Tavily 或撤销密钥后提问外部题：时间线 `tool_result → error`（`provider_unavailable`，可重试标记），单源失败不拖垮健康来源；缺 LLM 配置则任务 `failed` + `config_missing`，绝不返回伪造答案。

安全样例（无登记引用/伪证据/越权工具/超预算/摘要冒充全文）在 `eval/runner.py` 每次运行必跑且必须全部拒绝。

## 测试与评测

```bash
# 新契约（providers/evidence/tools/agent/ingest/tests_bridge）
knowledge_engine/.venv/bin/python -m pytest providers/tests evidence/tests tools/tests agent/tests ingest/tests tests_bridge -q
# researcher（含 /api/v1、SSE、云配置、JWT/限流/指标）
cd researcher/deep_research_system && python -m pytest tests/ -q
# 从仓库根目录用 researcher Python 环境运行三段式离线对照
python -m eval.runner --mode fake --freeze eval/baseline/three-stage.freeze.json --runs 1 --out eval/results/
```

- 设计与契约：[`docs/design.md`](docs/design.md) · 路线图与阶段验收：[`docs/roadmap.md`](docs/roadmap.md)
- 决策记录（只追加）：[`docs/decisions.md`](docs/decisions.md) · 测试基线：[`docs/testing.md`](docs/testing.md)
- P4 冻结件（题选/门槛/评分规则）：[`eval/baseline/round1.md`](eval/baseline/round1.md)
- 三段式运行时对照（固定混合 B、旧循环 C、共享图 D）：[`eval/baseline/three-stage.freeze.json`](eval/baseline/three-stage.freeze.json)
