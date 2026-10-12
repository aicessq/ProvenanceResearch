# 项目简报：ProvenanceResearch（供外部 AI 评审）

> 本文档为一次性评审材料，不含任何 API key、内部地址或用户数据，可整段粘贴给外部 AI。
> 里面所有"当前状态"的描述都是实测/走读结论，不是宣传口径。请严格区分"文档已写的目标"与"代码已实现的能力"。

---

## 1. 项目定位

本地自托管的**可溯源研究问答系统**（Agentic RAG）：用户提问后，Agent 通过受限工具调用三类来源——本地私有知识库（PDF/图片入库）、Web 搜索（Tavily）、学术论文（arXiv）——证据不足时自主追加检索，预算或 deadline 到达时停止；**每条事实性结论必须通过"引用闸门"（逐句可回指已登记证据）验证，验证不过就拒答**，不输出无据结论。

- 部署形态：本机单用户自托管（Docker Compose 起 PostgreSQL/Redis/Qdrant，应用本机跑）。
- 模型策略：**所有模型推理走云端**（LLM/embedding/rerank/OCR/vision 全部），不下载本地权重、不依赖 GPU；本地只做文件解析、切分、hash、FTS、RRF 等确定性处理。
- 项目性质：个人独立开发的作品集项目（原为两个旧私库的融合迁移，现升级为 Agentic RAG 目标）。

## 2. 仓库结构与技术栈

Monorepo，四个顶层目录：

| 目录 | 来源 | 职责 | 技术栈 |
| --- | --- | --- | --- |
| `knowledge_engine/`（KE） | 旧私库 RAG_sec 原样平移 | 文件/资产管理、PDF 解析入库、向量+FTS 索引、KB 检索 API、Celery 异步 ingest | FastAPI、Celery+Redis、PostgreSQL(alembic)、Qdrant、PyMuPDF、sentence-transformers（本地模型，历史遗留）、Vue |
| `researcher/deep_research_system/`（DRS） | 旧私库 MultiAgentIR_LangGraph 原样平移 | 多 Agent 研究编排、Tavily 搜索、SSE 流式任务、模型配置 | LangGraph、FastAPI+SSE、Redis 任务状态、Vue/Pinia |
| `frontend/`、`eval/`、`tests_bridge/` | 空 | P5 统一前端 / P4 评测 / P3 跨组件契约测试，均为占位 | — |
| `docs/` | 自撰 | design（目标规格）、roadmap（阶段+验收）、decisions（决策日志）、testing（测试基线）、architecture-audit（33 项审计发现）+ 4 张 draw.io 架构图 | — |

代码规模：KE 约 112 个 Python 文件 / 1.2 万行（另有 38 个测试文件）；DRS 约 78 个文件 / 0.9 万行（10 个测试文件）。两套旧 Vue 前端保留作过渡资产，P5 统一前端验收后才删。

## 3. 当前真实状态（最重要的部分）

**已完成（全部是"迁移 + 工程守护"，不含任何新功能）：**

- 两个旧项目源码零功能改动平移进 monorepo（搬运时 hash 比对无差异）。
- 测试基线实测：KE 96 passed（另有 34 个 integration 测试因本机无 Docker 未跑）；DRS 47 passed。
- GitHub Actions CI 实测全绿（6/6，约 2.2 分钟）：KE 测试、DRS 测试、两套前端构建、gitleaks 密钥扫描、仓库契约检查（校验评测语料 sha256、题集可溯源、文档互不矛盾、决策日志只追加）。
- 评测资产已交付：28 篇语料（21 入库 + 7 篇仓库外引用）+ 56 道人工题（覆盖纯 KB/必外网/论文/多步/无据拒答），全部 verified=false 待标注。
- 目标规格文档全部重写并互相咬合（P0R 阶段）；架构审计完成 33 项发现、4 张 draw.io 图（当前×2、目标拓扑、Agentic 运行时控制流）。

**未开始（P3a–P5 全部为零行实现）：**

- 云模型 Adapter（LLM/embedding/rerank/OCR/vision 的统一封装、协议契约、错误矩阵、多 key 池）
- PDF 扫描件云 OCR、图像云 vision、页/区域/bbox 级溯源入库
- kb_search/web_search/arxiv_search/source_fetch/evidence_read 五个工具与 Source Registry
- Agentic 有界循环、引用闸门、统一 /api/v1 + SSE
- 评测 runner、统一前端

一句话概括：**当前代码能力 = 两个旧项目的并集（固定流水线 RAG + 固定拓扑多 Agent 编排）；目标是把两者融合改造为"Agentic RAG + 全云模型 + 可溯源引用"。新旧之间隔着完整的 P3a–P5。**

## 4. 旧代码现状要点（架构审计摘要，全部有 file:line 证据）

**安全（现存活的洞）：**
- 两套栈所有 HTTP 端点零认证（含删除文档、查询、配置写入）；JWT/限流配置存在但未接线。
- DRS `POST /models/test` 接受任意 `api_base` 出站请求（类 SSRF 入口）；API key 明文写入 SQLite。
- Tavily 缺 key 或失败时**静默降级为 mock 搜索结果**（直接违反新契约"生产不返回 mock"）。
- KE 生成 LLM 失败时**静默降级为本地抽取式拼接答案**（违反"生成失败必须报错不伪造回答"）。
- DRS key 池兜底逻辑：拿不到本模型 key 时返回第一个非空任意槽位 key，跨供应商错配。
- PII/注入防护函数是死代码，运行时无任何防线。

**可靠性/并发：**
- KE 单 worker 容器默认 prefork，ingest/replace/recovery/reindex 全挤默认队列；`acks_late=False` 硬杀丢消息。
- 心跳是"阶段间调用"而非计时器：单阶段（解析/嵌入）超 180s 租约就被判死并 fencing，任务还在跑。
- Qdrant upsert 在 DB commit 之前，崩溃留孤立向量点无清理。
- DRS 的 YAML 拓扑声明的并发数/超时/重试旋钮**全部未实现**（搜索无信号量无超时直接 gather）——"看起来可控实际失控"。
- LLM 调用失败即硬失败整个任务，无重试无退避无 429/Retry-After 处理；熔断器写了但全仓无调用。
- DRS SSE 事件是进程内 asyncio.Queue 满即丢弃，无事件日志——目标要求的 Last-Event-ID 回放在现结构上不可能。

**正面事实（可复用的地基）：**
- KE 的 PG fencing 体系健全：`SELECT … FOR UPDATE SKIP LOCKED` + advisory lock 去重 + fencing token，多 worker 数据安全，是云化后 at-least-once 重派的现成地基。
- 两套测试套件全绿、CI 实测可信、评测资产与文档契约有可执行检查守护。

## 5. 目标架构（已定规格，概要）

```text
用户问题 → Agent 规划 → 受校验工具执行器
  ├─ kb_search      → knowledge_engine（云 embedding / FTS）
  ├─ web_search     → Tavily
  ├─ arxiv_search   → arXiv 元数据/摘要
  ├─ source_fetch   → 已登记来源正文/PDF
  └─ evidence_read  → 已登记 chunk/页/图片区域（需要时调云 vision）
工具结果 → 统一版本化 Evidence 池 → Reader（确定性 RRF 融合 + 可选云 rerank）
        → 判定证据缺口 → 有预算则追加检索，否则生成或拒答
        → 引用闸门（逐句验证 span/数字/专名，OCR 数字回看原图）
        → 回答（带 citation_id）或拒答
```

关键规格：
- **统一 Evidence 结构**（schema_version=2）：source_type（kb_chunk/web/paper/asset）× modality（text/image/mixed）× extraction（native_text/ocr/vision/provider_text）；locator 带页码/bbox（0–1 旋转校正坐标）/asset_id/hash；citation_id 由完整来源身份生成，前缀 K/W/A/I。
- **Agent 预算默认值**：最多 3 轮、12 次工具调用、20000 模型 token、180s 总 deadline、并发 4、可选费用硬上限（USD）；终止原因枚举（sufficient_evidence/budget_exhausted/deadline_exceeded/no_progress/cancelled/providers_unavailable/citation_gate_failed）。
- **Reader 融合**：确定性基线 RRF（KB 权重 1.0、外部 0.7，KB top-20/外部 top-10 → 最终 top-8）；可选云 rerank 在 RRF 之后；**无本地 reranker fallback**。
- **云模型契约**：LLM/EMBEDDING/RERANKER/OCR/VISION 五能力独立配置前缀；密钥只绑定相应 provider 不跨槽位；embedding 记录 provider/模型/维度/预处理身份，模型或维度变更 → 新 collection 重嵌入 → 验证后切换 + 回滚，禁止跨身份复用向量；失败矩阵区分缺配置/401/429/5xx/超时/畸形响应，仅暂态错误可有限重试。
- **出站双闸（隐私设计）**：`CLOUD_DATA_UPLOAD_ALLOWED=false` 总开关 + `CLOUD_DATA_APPROVALS_JSON`（能力→配置 fingerprint 的逐项授权）；换供应商/endpoint/model 使授权失效需重新确认；embedding 依赖的向量查询也受门禁，内部 FTS 不受限。
- **公共接口**：统一 `/api/v1` + problem+json 错误 + 版本化 SSE（meta/plan/tool_call/tool_result/source_status/evidence/token_delta/citation/done/error），支持 Last-Event-ID 回放。
- **部署裁决（已定）**：单机——DRS 单实例 + KE worker 多进程；不做分布式限流/分布式锁/跨实例熔断，不做 DRS 水平扩展（记为非目标）。
- **任务投递裁决（已定）**：at-least-once（acks_late=True + reject_on_worker_lost）+ ingest/control 双队列；PROCESSING 过时任务自动重派与"计时器心跳"捆绑上线，防双跑双烧钱。

## 6. 路线图与所处位置

| 阶段 | 内容 | 状态 |
| --- | --- | --- |
| P0/P1/P2（历史） | 骨架 + 两套源码零改动平移 | ✅ 完成 |
| 基线轮 | 测试基线 + CI + 配置模板 + Git 卫生 | ✅ 完成（CI 实测 6/6 绿） |
| P0R | 目标规格重冻结（design/roadmap/decisions/README/.env.example 互相咬合） | ✅ 文档完成；**云供应商尚未选择**（阻塞 P3a） |
| P3a | 云模型 Adapter 与配置/索引身份契约（fake HTTP 契约测试 + 错误矩阵，不是真云调用） | ❌ 未开始 |
| P3b | PDF/云 OCR/vision 可溯源入库（心跳计时器、租约 fencing、失败页不发布版本） | ❌ 未开始 |
| P3c | kb_search/Tavily/arXiv 工具 + Source Registry + SSRF 防护 | ❌ 未开始 |
| P3d | Agentic RAG 循环、Reader、引用闸门、/api/v1 + SSE | ❌ 未开始 |
| P4 | 评测与消融（A KB-only/B 外网/C 固定混合/D Agentic 各 3 次 + 去源消融；指标 Recall@k/MRR/引用准确率/拒答准确率/OCR CER/费用/p95） | ❌ 未开始（**数据集与题集已前置交付**） |
| P5 | 统一三栏前端（对话/证据/任务）+ 云服务配置 UI + 认证 | ❌ 未开始 |

治理规则：未达阶段验收不进下一阶段；每轮改动必须跑对应测试；设计决策必须追加进 decisions.md（带日期与理由，只追加不改写）；迁移期禁止顺手重构。

## 7. 已裁决 vs 待确认事项

**已裁决（2026-09-22）：**
- Q1 部署边界：单机、DRS 单实例 + KE 多进程；分布式协调整线不建。
- Q2 投递语义：at-least-once + 双队列，自动恢复与计时器心跳捆绑。

**待用户确认的推荐方案（审计轮产出，尚未拍板）：**
- Q3：Redis 定性为 DRS 硬依赖（掉线显式拒任务）；SSE 事件日志用每任务一条 Redis Stream（TTL 7 天）实现 Last-Event-ID 回放。
- Q4：降级只做**能力级**（云 rerank 失败保 RRF、向量失败保 keyword/外部源），不做**模型级 fallback**（不 glm→deepseek 换模型续跑）；LLM 池改为同 provider 多 key + 退避轮换。
- Q5：安全修复时序——P3a 必修 `/models/test` 任意出站与跨供应商 key 兜底；端点认证推 P5；本机单用户期间接受零认证风险（前提不暴露网络）。
- Q6：死配置/死代码不单独开清理轮，在对应阶段落地真契约时同批"接线或删除"。
- Q7：扩展功能不新开 scope，全部挂靠既有阶段验收（DRS 重启恢复立项否决）。

**其他未决：**
- 34 个 KE integration 测试未跑（本机 Docker daemon 未启动）。
- 评测语料中 5 篇扫描件的处理方式待裁决（OCR 用例素材 vs. 弃用）。
- 56 题全部 verified=false，人工标注未开始（P4 冻结阈值的前置）。

## 8. 请你（评审 AI）回答的问题

1. **完成度评估**：对照第 6 节路线图，给出你的独立判断——这个项目离"可演示的最小可用人"还有多少工作量？哪些阶段的工作量最容易被低估？
2. **规格与顺序的修改建议**：P3a→P3b→P3c→P3d 的顺序是否合理？有没有应该提前/合并/拆开的？验收标准有没有互相冲突或不可测试的？
3. **实现风险**：引用闸门（逐句 span 验证）、SSE 回放（Redis Stream 方案）、embedding 身份与索引迁移——这三个规格哪条最容易在实现时走样？有什么更简单的等价做法？
4. **范围建议**：作为个人作品集项目，P3–P5 是否过大？如果只能保三个卖点（可溯源引用、Agentic 追加检索、全云多模态），你会砍掉/推迟哪些验收项？
5. **第二意见**：对第 7 节 Q3–Q7 的推荐方案，逐条给出赞同或反对及理由。
6. **补盲**：以上简报有没有漏掉你认为评审前必须知道的关键事实？请列出需要补充的问题清单。

---
*生成于 2026-10-10；对应仓库 commit f50a2c8 之后的工作区状态（docs 下有未提交的 architecture-audit 与架构图）。*
