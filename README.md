# research_agent

私库 + 网络 + 学术来源的 Agentic RAG 研究系统：Agent 通过受限工具调用选择私库、网络与论文来源，在证据不足时追加检索，在预算或 deadline 到达时停止；所有结论必须通过引用闸门，否则拒答。

这是一个面向本地自托管的 monorepo：用户下载项目，在本机运行基础设施，自己配置云端 LLM、embedding、reranker、OCR、vision 及搜索凭证。**当前文档已更新目标规格，供应商契约仍待确认，代码尚未实现这些新能力。**

| 目录 | 来源 | 目标职责 |
| --- | --- | --- |
| `knowledge_engine/` | RAG_sec | 本地原文件与资产管理、PDF/图像入库、云 OCR/vision/embedding、索引与 KB 工具 |
| `researcher/` | MultiAgentIR_LangGraph | Agentic RAG 编排、工具执行器、Tavily/arXiv/source adapter、Reader、引用闸门与公共 API |
| `frontend/` | — | P5 统一研究界面与云服务配置；当前占位 |
| `eval/` | — | 固定检索、Agentic、来源扩展与 PDF/OCR/vision 分层评测；当前占位 |
| `tests_bridge/` | — | Evidence、工具、云 Adapter、Agent 轨迹、SSE 与引用契约测试；当前占位 |
| `docs/` | — | 目标设计、路线图、决策与测试基线 |

- 目标设计（Evidence / Agentic loop / source registry / PDF/OCR/vision / 云模型 / 引用闸门）：[`docs/design.md`](docs/design.md)
- 迁移与演进阶段验收：[`docs/roadmap.md`](docs/roadmap.md)
- 决策记录：[`docs/decisions.md`](docs/decisions.md)
- 既有测试基线：[`docs/testing.md`](docs/testing.md)

## 快速开始（当前仅基础设施）

```bash
cp .env.example .env
# 先保持 CLOUD_DATA_UPLOAD_ALLOWED=false；用户核对供应商地域/留存条款后，
# 再填写 LLM_*/EMBEDDING_*/RERANKER_*/OCR_*/VISION_* 与 TAVILY_API_KEY。
docker compose up -d   # postgres:16 + redis:7 + qdrant
```

根 Compose 目前只启动 PostgreSQL、Redis、Qdrant，不提供云模型服务。云端模型（含 rerank）和外部搜索会把必要的查询、候选证据、PDF 页面或图片发送给用户选择的供应商；凭证和来源启用不等于上传授权。目标要求总开关及 `CLOUD_DATA_APPROVALS_JSON` 中能力/供应商配置身份授权均匹配，更换供应商或 endpoint/model 后重新核准。用户必须自行确认地域、留存、隐私与费用政策。真实密钥只放在被 `.gitignore` 忽略的 `.env` 或未来的后端加密配置中，不进仓库、日志、SSE 或前端 `localStorage`。这些出站/加密规则尚待实现，当前模板默认值不是运行时已阻断外送的证明。

## 当前状态

- 旧迁移基线保留：`knowledge_engine` 的 96 个非 integration 测试通过、`researcher` 的 47 个原测试通过；34 个 knowledge_engine integration 测试尚未运行。
- 新目标规格已更新为 P0R → P3a/P3b/P3c/P3d → P4 → P5；供应商契约尚待确认，Agentic RAG、arXiv、云 embedding/reranker/OCR/vision、PDF/图像增强仍未实现。
- 两套旧前端作为过渡资产保留，等 P5 统一前端完成并验收后再移除；不在迁移期提前删除或重写。
- 实际进入下一阶段前必须满足 [`docs/roadmap.md`](docs/roadmap.md) 对应“验收”行。
