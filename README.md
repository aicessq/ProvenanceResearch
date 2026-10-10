# Provenance Research

[![CI](https://github.com/aicessq/ProvenanceResearch/actions/workflows/ci.yml/badge.svg)](https://github.com/aicessq/ProvenanceResearch/actions/workflows/ci.yml)

> Built an evidence-grounded Agentic RAG research system that autonomously expands retrieval across private knowledge bases, web sources and academic papers under explicit budget constraints. Every factual claim is verified against registered provenance evidence, with reproducible evaluation against non-agentic baselines.

私库 + 网络 + 学术来源的 **证据可溯源 Agentic RAG** 研究系统：Agent 在显式预算（轮次/工具调用/token/deadline）内自主决定调用 `kb_search` / `web_search` / `arxiv_search` 等白名单工具，证据缺口驱动追加检索；每条事实性结论必须通过**引用闸门**（登记存在 → 范围覆盖 → 数字/专名字面 → 语义复检），否则如实拒答。回答结局（answered/refused）与任务生命周期（completed/failed/cancelled）严格分开。

## 系统组成

| 目录 | 职责 |
| --- | --- |
| `providers/` | 云模型适配层：LLM/OCR/vision（一真一假）、错误六分类、EmbeddingIdentity |
| `evidence/` + `tools/` | 统一 Evidence v2（来源身份/版本/范围）、五工具执行器（白名单+SSRF 防护） |
| `agent/` | 有界 Agent Loop、Reader RRF、Citation Gate、预算硬边界 |
| `ingest/` | PDF/图像入库：native → OCR → vision 逐页回退，bbox/hash/图注关联到 citation |
| `eval/` | P4 冻结评测：A KB-only / B 固定混合 / C Agentic 对照 + 指标 + 安全样例 |
| `researcher/deep_research_system/` | 公共接口 `/api/v1`（任务生命周期 + 版本化 SSE + 云配置面 + JWT/限流/指标） |
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

1. **无证据拒答**——提问"IETF 计划什么时间发布 TLS 1.4？"：语料/网络都给不出可靠依据 → `answer.status=refused`（`requires_prediction`），任务仍 `completed`，时间线可见停止原因。
2. **来源冲突**——提问 2016 与 2025 版《网络安全法》条款对照（如"修改决定列为第几条"）：证据面板并列展示两个版本的原文页（`zh_cybersec_amend_2025` 与重新公布版），答案只引用各自版本的 citation，不同版本不误并。
3. **provider failure**——断开 Tavily 或撤销密钥后提问外部题：时间线 `tool_result → error`（`provider_unavailable`，可重试标记），单源失败不拖垮健康来源；缺 LLM 配置则任务 `failed` + `config_missing`，绝不返回伪造答案。

安全样例（无登记引用/伪证据/越权工具/超预算/摘要冒充全文）在 `eval/runner.py` 每次运行必跑且必须全部拒绝。

## 测试与评测

```bash
# 新契约（providers/evidence/tools/agent/ingest/tests_bridge）
knowledge_engine/.venv/bin/python -m pytest providers/tests evidence/tests tools/tests agent/tests ingest/tests tests_bridge -q
# researcher（含 /api/v1、SSE、云配置、JWT/限流/指标）
cd researcher/deep_research_system && python -m pytest tests/ -q
# P4 评测（fake=机械自检；live 需云凭证，结果含均值/95% CI）
python3 eval/runner.py --mode fake --out eval/results/
```

- 设计与契约：[`docs/design.md`](docs/design.md) · 路线图与阶段验收：[`docs/roadmap.md`](docs/roadmap.md)
- 决策记录（只追加）：[`docs/decisions.md`](docs/decisions.md) · 测试基线：[`docs/testing.md`](docs/testing.md)
- P4 冻结件（题选/门槛/评分规则）：[`eval/baseline/round1.md`](eval/baseline/round1.md)
