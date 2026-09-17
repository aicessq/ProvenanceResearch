# 迁移路线图与阶段验收

本文件是根 `AGENTS.md`「每个阶段有明确的验收标准（见各阶段'验收'行）」所引用的权威来源。
规则：**未达成本阶段验收，不进入下一阶段。**

## 命名辨析（重要）

仓库里存在两套互不相干的「Phase」编号，不要混用：

| 编号体系 | 位置 | 含义 |
| --- | --- | --- |
| **Phase 0–10**（旧） | `knowledge_engine/Doc/文档2.MD`、`knowledge_engine/README.md` | RAG_sec 子系统**自身**的实现历史，与本次合并无关 |
| **P0–P5**（本文件） | 本文件 | 新仓库 research_agent 的迁移与集成路线 |

## 阶段总览

| 阶段 | 目标 | 状态 |
| --- | --- | --- |
| P0 | 规格与骨架 | 已完成（2026-09-17） |
| 基线轮 | 工程基线：测试可复现、CI 就位、可 diff | 进行中 |
| P1 | 平移 RAG_sec 作为知识引擎 | 搬运已完成，验收在基线轮落实 |
| P2 | 平移 MultiAgentIR 作为编排层 | 搬运已完成，验收在基线轮落实 |
| P3 | 桥接（核心） | 未开始 |
| P4 | 评测与消融 | 未开始 |
| P5 | 前端重写 | 未开始 |

## P0 — 规格与骨架

- **内容**：固定六目录；两项目原样复制搬入；根 `docker-compose.yml` 只含 PostgreSQL/Redis/Qdrant；`docs/design.md`（证据模型 / 工具契约 / 融合 / 引用闸门 / 评测）与 `docs/decisions.md` 成文；环境变量契约定为 `LLM_MODEL`/`LLM_API_KEY`/`LLM_BASE_URL`。
- **验收**：六目录存在；`docs/design.md` 五节 + 非目标齐全；搬入逐文件 sha256 比对为空 diff。
- **状态**：已完成。证据见 `docs/decisions.md`（2026-09-17 各条）。

## 基线轮 — 工程基线

- **内容**：跑通两个子系统测试并记录真实基线；补根 `.env.example`；把本路线图与验收成文；凭证复查；首次基线提交；CI 第一版（只跑既有测试 + 密钥扫描）。
- **不做什么**：不改任何业务代码；不加 ruff/mypy/格式门禁；不进 integration 测试与 service container。
- **验收**：
  1. 两个子系统各自给出可复现命令与通过/失败数，失败项有分类（环境问题 / 代码问题）——记录于 `docs/testing.md`。
  2. 根 `.env.example` 存在，README 的 `cp .env.example .env && docker compose up -d` 路径自洽。
  3. `docs/roadmap.md` 含逐阶段验收（本文件）。
  4. 首次提交完成，后续任何改动能算 diff。
  5. CI 在 PR 上跑 knowledge_engine 单元测试、researcher 测试、gitleaks，且全绿。

## P1 — 平移 RAG_sec 作为知识引擎

- **内容**：`knowledge_engine/` 整目录（含其自带测试）作为私库知识引擎落地，只允许改包名与配置路径，功能零改动。
- **验收**：`knowledge_engine/backend/tests` 原测试全绿（非 integration）；integration 测试在真实 PG/Redis/Qdrant 下另行通过。
- **备注**：搬运已在 P0 完成；本阶段验收在基线轮首次实际执行。具体数字见 `docs/testing.md`。

## P2 — 平移 MultiAgentIR 作为编排层

- **内容**：`researcher/` 整目录（含其自带测试）作为检索编排层落地，搜索先用 mock。
- **验收**：`researcher/deep_research_system/tests` 原测试全绿。
- **备注**：同 P1，验收在基线轮首次实际执行。

## P3 — 桥接（核心）

- **内容**：
  1. 统一 `Evidence` 模型（`source_type` / `provenance` / `score` / `raw_text` / `citation_id`）与 `K-`/`W-` 稳定引用号生成、URL 规范化。
  2. 两个同构 Searcher 工具适配器：`kb_search`、`web_search`（只召回、不融合，失败返回空证据 + error）。
  3. Reader 三路融合：KB vector top-20 + KB keyword top-20 + Web top-10，RRF `k=60`，权重 `1.0/0.7`，截 top-8。
  4. 引用闸门：逐句引用、原文机检 + 语义复检、失败重试 1 次、再失败拒答。
  5. 统一 `/api/v1` 公共接口与版本化 SSE 事件契约（`meta`/`plan`/`evidence`/`token_delta`/`citation`/`done`/`error`，含 `Last-Event-ID` 回放）。
- **验收**：`tests_bridge/` 契约测试全绿——每条断言可观察行为（如「KB 命中带 chunk 溯源」『网络命中带 URL』「闸门拒绝无据结论」）；旧接口保持可用，旧测试仍全绿。
- **硬约束**：允许改动的只有桥接点。发现旧代码需要改动时，先记入 `docs/decisions.md` 再动。

## P4 — 评测与消融

- **内容**：迁移 RAG_sec golden set，新增「必须外网才能答」的题目；同一问题集跑纯私库 / 纯网络 / 融合三组，每组 3 次。
- **验收**：产出可复现的对比数字（Recall@5/10/20、MRR、引用准确率、拒答准确率、答案正确率），且融合组五项指标不低于单源组；否则回到 `docs/decisions.md` 调整融合常量并重跑。

## P5 — 前端重写

- **内容**：一屏三栏（研究对话流 / 证据与引用面板 / 会话与任务控制），按 P3 冻结的 SSE 与证据契约开发；复用 MultiAgentIR 已验证的 SSE 流式处理与 Pinia 多会话管理。
- **前置**：P3 的后端契约冻结。顺序反了会边写边改。
- **验收**：引用可点开原文；KB chunk 与 URL 混排显示；多会话并发不串流。

## CI / CD 归属

| 项 | 归属阶段 | 说明 |
| --- | --- | --- |
| 单元测试 + gitleaks 门禁 | 基线轮 | 本轮落地 |
| integration 测试（PG/Redis/Qdrant service container） | 基线轮之后、P3 期间 | 等 Docker 守护进程稳定后作为 main/定时任务 |
| OpenAPI 兼容性检查 | P3 | 跟随 `/api/v1` 契约冻结 |
| tag 触发的多架构镜像 + compose 发行包 | P3 之后 | 前提是 compose 里有服务可发布 |