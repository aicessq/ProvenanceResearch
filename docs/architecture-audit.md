# 架构审计与拷问记录

> 2026-09-22 开始。范围：忽略迁移历史包袱，对照 [design.md](design.md) 目标规格，审视当前两套子系统的架构问题。
> 缩写：DRS = `researcher/deep_research_system`，KE = `knowledge_engine/backend`。
> 本文件是交互式拷问的工作记录：发现先记为「待裁决」，逐题裁决后更新状态；正式决策按 AGENTS.md 惯例追加到 [decisions.md](decisions.md)。本审计本身不改代码。
>
> 状态取值：**已覆盖** = 路线图/design 已有对应方案（届时必须落实）；**缺口** = 目标文档未覆盖，需要裁决；**裁决见** = 已在拷问记录中定论。

## A. 安全

| # | 发现 | 证据 | 状态 |
| --- | --- | --- | --- |
| A1 | KE 所有端点无认证（含删除文档、eval、query），`api/admin.py` 是空 stub | KE `app/api/upload.py:37`、`documents.py:37,81,149`、`query.py:39,84,120`、`admin.py:7` | design §9 只要求「开放到网络前必须认证」；本机单用户下接受风险还是提前修 → 裁决见 Q5 |
| A2 | DRS `POST /models/test` 接受任意 `api_base` + 调用方密钥并出站请求，且无认证 | DRS `app/api/routes_models.py:64-79` | 类 SSRF 现存入口；P3a 出站闸门管模型 endpoint，但这个入口在 P3a 之前是活的 → 裁决见 Q5 |
| A3 | DRS `PUT /models/config` 将 API key 明文写入 SQLite `data/config.db` | DRS `app/services/config_service.py:88-101` | P5 加密存储（CONFIG_ENCRYPTION_KEY）覆盖终点，明文现状存续期 → 裁决见 Q5 |
| A4 | `redact_pii` / `detect_injection` 是死代码，运行时无任何注入/PII 防线 | DRS `app/core/security.py:8-33`，全仓无调用 | P3c 工具结果注入样句要求覆盖；当前为零，已覆盖（P3c） |
| A5 | Tavily 缺 key 或调用失败时静默降级为 mock 搜索结果 | DRS `app/services/search_service.py:26-51` | 直接违反「生产不返回 mock」契约；P3c 必须移除，已覆盖（P3c） |
| A6 | KE 容器以 root 运行；默认弱凭证（PG `cybersec`、Redis 空密码） | KE `backend/Dockerfile`（无 USER）、`.env.example:21,29` | 基础设施卫生，未排期 → 裁决见 Q7 |
| A7 | CORS `allow_credentials=True` + `allow_methods/headers=["*"]` | KE `app/main.py:46-52` | 本机模式低风险；网络暴露前必须收紧，已覆盖（design §9） |
| A8 | DRS 全部路由无认证；JWT/SECRET_KEY/限流配置存在但未接线 | DRS `app/api/routes_research.py`、`config.py:133-138` | 同 A1 处置 |

## B. KE worker 并发

| # | 发现 | 证据 | 状态 |
| --- | --- | --- | --- |
| B1 | 单 worker 容器，Celery 默认 prefork + 默认并发，ingest/replace/recovery/reindex 全部挤在默认队列，无队列分离/优先级 | KE `docker-compose.yml:146`、`workers/celery_app.py:18-22` | → 裁决见 Q1/Q2 |
| B2 | `task_acks_late=False`：worker 硬杀即丢消息；恢复扫描只重派 queued-stale，PROCESSING 默认判 failed 不重跑 | KE `workers/celery_app.py:31-34`、`recovery_worker.py:129-133` | 语义取舍 → 裁决见 Q2 |
| B3 | 心跳是「阶段间调用」而非计时线程：单阶段（解析/嵌入）超过 180s 租约即被判过期并 fencing，任务还在跑却已被判死（云化后单阶段更长，且在烧钱） | KE `workers/ingest_worker.py:71-112`、`config.py:71` | P3b「长云调用需持续心跳」已覆盖，但需明确为计时器心跳 + INGEST 并发闸 |
| B4 | Qdrant upsert 发生在 `db.commit()` 之前，`fail()` 不回滚已写向量 → 崩溃留下孤立向量点，无清理 | KE `services/index_service.py:99`、`ingest_worker.py:110` | P3b「索引清理」已覆盖 |
| B5 | PG fencing 体系本身健全：`SELECT … FOR UPDATE SKIP LOCKED` + advisory lock 去重 + fencing token，多 worker 实例数据安全 | KE `services/ingest_task_service.py:72,159`、`upload_service.py:151` | 事实记录：多实例 KE worker 的正确性地基已在 |
| B6 | 本地 embedding/reranker 按 prefork 子进程各加载一份（内存 ×N） | KE `services/embedding_service.py:207-210` | P3a 全云化后自动消失，已覆盖（P3a） |
| B7 | 死配置/死任务：`reindex_collection_task` 从未被派发；`TASK_STATUS_REDIS_TTL_SECONDS`、`WORKER_HEARTBEAT_INTERVAL_SECONDS` 无任何使用 | KE `workers/reindex_worker.py:12`、`config.py:70,76` | → 裁决见 Q6 |

## C. Redis 用途

| # | 发现 | 证据 | 状态 |
| --- | --- | --- | --- |
| C1 | KE 侧 Redis 仅当 Celery broker + result backend + 健康_ping；无缓存、无锁（分布式协调全在 PG） | KE `config.py:168-175`、`dependencies.py:56-68` | 事实记录 |
| C2 | DRS Redis 仅作任务状态存储（TTL 7d）；Redis 掉线时静默降级为「不持久化但任务照跑」 | DRS `core/redis_client.py:117-137` | 违反「显式失败」精神 → 裁决见 Q3 |
| C3 | DRS 任务结果缓存在进程内存 dict（md5 键、无 TTL、无上限），长期运行内存只增不减 | DRS `services/research_service.py:33,211-218` | → 裁决见 Q3 |
| C4 | 两套栈各自独立 Redis 实例；根 compose 另有一套共享 infra 未接线 | KE/DRS 各自 `docker-compose.yml`、根 `docker-compose.yml` | → 裁决见 Q4 |
| C5 | SSE 事件目前是 `asyncio.Queue` + 满即丢弃，无事件日志 → 目标 P3d 要求的 Last-Event-ID 回放/终态重连在当前结构上不可能 | DRS `research_service.py:79-84` | 缺口：事件日志的载体与归属 → 裁决见 Q3 |

## D. 工具

| # | 发现 | 证据 | 状态 |
| --- | --- | --- | --- |
| D1 | DRS agent 只有一个真实工具（Tavily 搜索，进程内 httpx）；无 kb_search / arXiv / source_fetch / evidence_read | DRS `agents/searcher.py:103-107` | P3c 既定工作，已覆盖 |
| D2 | 「看起来可控实际失控」：topology/agents YAML 声明 `max_concurrent_searchers`、`searcher_timeout_seconds`、agent 级 `max_retries/timeout` 全部未实现——搜索无信号量无超时直接 gather | DRS `config/topology.yaml`、`graphs/hierarchical_graph.py:104-116`、`agents.yaml` | P3d 工具执行器须落实真旋钮，已覆盖（P3d）；死配置处置 → 裁决见 Q6 |
| D3 | `MAX_CONCURRENT_SEARCHES` 配置未用 | DRS `config.py:121` | 同 D2 |

## E. LLM API 池与降级

| # | 发现 | 证据 | 状态 |
| --- | --- | --- | --- |
| E1 | DRS「key 池」是退化的：每模型从单一 env 合成恰好 1 把 key，轮询空转 | DRS `model_pool/key_pool.py:36-49`、`core/config.py:289-298` | 池的真实规模与形态 → 裁决见 Q4 |
| E2 | `KeyCircuitBreaker` 全仓无任何运行时调用（死代码）；且 APIKeyPool/LLMClient 按 graph 构建各自实例化，熔断状态本就不共享 | DRS `model_pool/circuit_breaker.py:5-44`、`graphs/hierarchical_graph.py:366-379`、`api/routes_models.py:29-30` | 缺口：熔断/重试要不要真正接线、状态放哪 → 裁决见 Q4 |
| E3 | `get_api_key` 兜底逻辑：拿不到本模型 key 时，返回**第一个非空的任意槽位 env key**，不分 provider 直接用 → 跨供应商错配、神秘 401、密钥发往错误厂商 | DRS `model_pool/key_pool.py:51-56`（已亲自核验） | 违反 P3a「密钥只能绑定相应 provider」；必须移除，已覆盖（P3a） |
| E4 | LLM 调用失败即硬失败整个任务（仅 search 分支 `return_exceptions=True` 吞错）；无重试、无退避、无 429/Retry-After 处理 | DRS `model_pool/client.py:114-117`、`research_service.py:269-274` | P3a 失败矩阵已覆盖 |
| E5 | KE 生成链路：单 key、同步 httpx、单次尝试、30s 超时；`LLMServiceError` 时静默降级为 `deterministic-evidence-summarizer` 抽取式拼接答案（`model_name` 字段可见） | KE `services/llm_service.py:37,69`、`answer_generator.py:83-86`（已亲自核验） | 直接违反「生成 LLM 失败必须报 provider 错误，不伪造成功回答」；P3a 必须移除，已覆盖（P3a） |
| E6 | 降级语义现状与目标的落差：目标只定义了**能力级**降级（云 rerank 失败保 RRF、向量失败保 keyword/web、生成失败拒答/报错），未定义**模型级** fallback（如 glm→deepseek 换模型续跑） | design §5-6 | 是否引入模型级降级 → 裁决见 Q4 |

## F. 同一工具被多实例并发使用

| # | 发现 | 证据 | 状态 |
| --- | --- | --- | --- |
| F1 | 目标下 `kb_search` 走内部 HTTP 调 KE：并发查询本身 FastAPI/Qdrant 可扛，但**每次向量检索都触发一次云 embedding 调用** → 并发 agent 任务 = 并发 embedding 调用，429 风险，且查询 embedding 无缓存 | design §3 | 缺口：查询 embedding 的并发闸与缓存 → 裁决见 Q4 |
| F2 | arXiv 要求「初始请求间隔 3 秒」是全局限额：单进程 semaphore 挡不住多实例/多任务并发 | design §3 | **已裁决（Q1）**：DRS 单实例 → 单进程 semaphore 落实，不建分布式限流；多任务并发另受 AGENT_MAX_CONCURRENCY 约束 |
| F3 | `INGEST_MAX_CONCURRENCY=2` 目标未实现（当前 worker 并发 = CPU 核数，不受此约束） | design §7 | P3b 落实，已覆盖（P3b） |

## G. 扩展功能候选（全部未排期，是否入 scope）

G1 SSE 事件日志/回放（= C5，P3d 验收必需）；G2 DRS 任务重启恢复（现在重启即 RUNNING→FAILED 清孤儿，无恢复）；G3 admin 端点（= A1）；G4 成本核算看板（P4 已含指标，看板未含）；G5 KE 就绪/健康探针已有部分（dependencies 健康检查）；G6 OpenAPI 契约冻结检查（P3d 已含）。→ 裁决见 Q7。

## 拷问记录

### Q1：多实例的真实边界（2026-09-22 裁决）

**问题**：多实例边界决定分布式限流、队列迁移、Redis 锁整条线要不要存在。产品定位是本机单用户（design §1），但用户关注多实例并发，需钉死规模假设。

**过程**：用户先追问四个选项利弊。摊开后结论：researcher 水平扩展代价最大（DRS `_tasks/_running/_subscribers/取消句柄` 全是 asyncio 内存态，外移等于重写任务执行层，且推翻 P3d「旧任务生命周期保持」约束），单用户下收益为零；KE 多容器与 KE 多进程的实际差距比字面小——P3b 做完心跳计时器/孤立点清理后只差存储层与 CI 矩阵。

**裁决**：单机部署——researcher 单实例 + KE worker 多进程（prefork）。「researcher 多实例/多机水平扩展」记为非目标，与 design §11 多租户非目标一致。

**推论**：
- 不建分布式限流、分布式锁、跨实例熔断状态共享。arXiv 3 秒间隔用 DRS 单进程 semaphore 落实（F2 关闭）。
- SSE 事件日志只需单进程写入（载体裁决移交 Q3，C5）。
- DRS 单实例的已知代价显式接受：进程挂 → 在跑任务死亡，重启清孤儿不恢复；是否补恢复机制 → Q7（G2）。
- KE 多进程为默认形态；多容器/多机维度关闭，队列分离维度移交 Q2。

**对应发现更新**：F2 关闭；B1 的多容器维度关闭；C5/G2 移交后续题。

### Q2：KE 任务投递/恢复语义（2026-09-22 裁决）

**问题**：现状 `task_acks_late=False`（硬杀丢消息）+ 恢复扫描默认只重派 queued-stale、PROCESSING 过时任务判 failed（`TASK_AUTO_RECOVER_PROCESSING=false`）→ 崩溃 = 任务死亡 + 云费用白烧；而 claim/fencing 幂等地基本就为重派设计，at-least-once 几乎免费。风险点：心跳是阶段间调用，活着的长阶段任务与死任务不可区分，提前开自动恢复会双跑双花。

**裁决**（记为 P3b 落实时的既定设计，本轮不改代码）：
- `task_acks_late=True` + `task_reject_on_worker_lost=True`：硬杀不丢消息，重派由现有 fencing 保证幂等。
- 双队列：`ingest`（重）+ `control`（recovery/reindex，轻），recovery 扫描不被长 ingest 堵死。
- `TASK_AUTO_RECOVER_PROCESSING` 的开启与 **P3b 计时器心跳捆绑**：心跳落地前维持 fail-fast，防双跑双花；心跳落地后 PROCESSING 过时任务改为重派（fencing 防旧 worker 发布）。

**对应发现更新**：B1（队列分离）、B2 关闭，落实点在 P3b；B3 补充明确「计时器心跳」为 P3b 硬性内容。

### Q3：DRS 侧 Redis 定性与 SSE 事件日志载体（2026-09-22，待确认）

**问题**：Redis 掉线时 DRS 静默不持久化但任务照跑（违反显式失败精神）；SSE 事件是进程内 Queue 满即丢弃、无事件日志，P3d 的 Last-Event-ID 回放/终态重连验收无法兑现。

**推荐方案（本轮未获用户确认，暂记待确认）**：
- Redis 定性为**硬依赖**：任务创建时 Redis 不可用 → 显式拒绝（problem+json），不再静默照跑。
- SSE 事件日志用**每任务一条 Redis Stream**（TTL 7d 对齐状态存储）：Last-Event-ID 直接用 stream entry ID，重连/回放读 Redis；在线分发仍走进程内 queue（满则丢，有 Stream 兜底）。单进程写入（Q1 裁决）使该方案无并发写风险。
- KE 侧维持 broker 角色；无人消费的 result backend 待核后移除（B7 类死配置）。
- C3 内存结果缓存就地加 TTL + 上限，不新增 Redis 角色。
- 目标拓扑：一个 Redis 实例、两个逻辑 DB（broker / state），记入 P5 拓扑；两栈各一个实例的现状只是过渡。

**待确认**：用户未作答；后续收尾时一并请确认。若用户选择维持尽力而为，需同步修改 P3d 回放验收。

### Q4：LLM API 池形态与降级层级（2026-09-22，待确认）

**问题**：池是退化的（每模型 1 key、轮询空转），熔断器全仓无调用、按 graph 各自实例化，key 兜底跨供应商错配；分叉在降级定在哪一层——design 只定义能力级降级，未定义模型级 fallback。

**推荐方案**：**能力级降级，不换模型续跑**。
- P3a 把池做实：每能力支持多 key（同 provider，列表配置）；`LLMClient` 接线 `record_success/record_failure`；池从按 graph 实例化改为进程级单例（Q1 下单进程即全局）；**删除 `key_pool.py:51-56` 跨供应商兜底**（P3a 契约本就要求密钥不跨槽位借用）。
- 429/5xx 语义：同 key 尊重 Retry-After 退避重试，再轮换下一 key；全部 key 熔断 → `providers_unavailable` 终止并诚实报错，不伪造成功。
- **不做模型级 fallback**（如 glm→deepseek 续跑）：换模型会污染 P4 的模型身份冻结、成本对比与引用可复现性，且违反 design「生成 LLM 失败报告 provider 错误」契约；韧性靠多 key + 退避提供。
- F1：kb_search 查询 embedding 加有界缓存（键 = query + embedding 身份，短 TTL，缓存命中计入 meta）——P4 每组同题复跑 3 次，直接省钱且降低方差。
- KE 侧 E5（静默确定性降级）按 P3a 契约移除，无争议。

### Q5：安全修复时序（2026-09-22，待确认）

**问题**：哪些安全洞在 P3a 前就修，哪些按既定路线走。现存活入口：`/models/test` 任意 base_url 出站（A2）、SQLite 明文 key（A3）、全端点零认证（A1/A8）。

**推荐方案**：
- **P3a 必含**（契约必然 + 入口现在就是活的）：A2——`/models/test` 锁定到已登记模型 endpoint 白名单或直接移除；E3——删跨供应商 key 兜底（已覆盖项，强调为 P3a 硬性内容）。
- A3（明文 SQLite key）：P3a 统一 env/能力前缀契约后，运行时 key 走 `.env`（已 gitignore），SQLite 配置路径停止增殖；P5 加密存储 + UI 配置为终点。
- A1/A8（认证）：按 design §9「开放到网络前必须认证」，与 P5 配置接口一起交付；本机单用户期间记为**接受的风险**（边界条件：不得暴露到网络）。
- A5（Tavily 静默 mock）：P3c 移除（已覆盖）。
- A6（root 容器、弱默认凭证）：P5 打包加固（Dockerfile USER 指令、compose 强制 env 凭证）。

### Q6：死配置/死代码处置（2026-09-22，待确认）

**问题**：死旋钮是"看起来可控实际失控"，但迁移期禁止顺手重构。

**推荐方案**：不动现状，登记死配置清单，在对应阶段落地真契约时**同一批次接线或删除**：`WORKER_HEARTBEAT_INTERVAL_SECONDS`（P3b 计时器心跳真用它）；`TASK_STATUS_REDIS_TTL_SECONDS`（若 Q3 采纳 Redis Stream 则删除或改指 Stream TTL）；`reindex_collection_task`（P3a 索引迁移/回滚的自然派发点，届时不再是死任务）；DRS 的熔断器与 agent 级 `max_retries/timeout` 旋钮（P3a/P3d 接线）。原则：优先接线（多数是目标真需要的），其次删除；不单独开"清理轮"。

### Q7：扩展功能与基础设施卫生是否入 scope（2026-09-22，待确认）

**推荐方案**：不新开 scope，全部挂靠既有阶段验收：
- G2（DRS 任务重启恢复）：**不立项**。单实例已知代价在 Q1 显式接受；本机单用户重启频率低、任务时长有 AGENT_DEADLINE_SECONDS=180 兜底，重触发成本可接受。记为非目标。
- G4（成本看板）：P4 已含指标输出，看板是 UI 工作 → P5 顺带，不单独立项。
- G5（DRS /health）：并入 P3d 公共接口（`/api/v1` 统一后顺手），最小实现（redis ping + 进程存活）。
- A6 基础设施卫生 → P5（同 Q5）。
- 一句话原则：任何扩展需求必须挂到某个既有阶段的验收行上，否则不进 roadmap。

## 收尾状态（2026-09-22）

- 架构图（draw.io，可编辑）：当前实现两张 [architecture-current-knowledge-engine.drawio](architecture-current-knowledge-engine.drawio)、[architecture-current-researcher.drawio](architecture-current-researcher.drawio)；目标系统拓扑一张 [architecture-target.drawio](architecture-target.drawio)；Agentic 自主决策、工具选择与观察反馈闭环单独见 [architecture-target-agentic-rag-runtime.drawio](architecture-target-agentic-rag-runtime.drawio)。拓扑图绿底 = Q1/Q2 已裁决，黄底 = Q3–Q7 推荐待确认。
- 已确认裁决：Q1（部署边界）、Q2（投递语义）——已入册 `docs/decisions.md`。
- 待确认推荐：Q3（Redis 硬依赖 + Stream 事件日志）、Q4（能力级降级不换模型）、Q5（安全修复时序）、Q6（死配置接线制）、Q7（扩展不新开 scope）。
- 待用户确认后：把上述推荐按 decisions.md 惯例追加；若否决某项，回写对应 Q 节与发现表。
