# 系统架构与代码阅读指南

本文档面向希望运行、理解或扩展 MultiAgentIR 的开发者。文中路径均以仓库根目录为基准；后端命令需在 `deep_research_system/` 下执行，前端命令需在 `deep_research_system/frontend/` 下执行。

## 1. 项目定位

MultiAgentIR 是一个基于 **FastAPI + LangGraph + Vue 3** 的多 Agent 深度研究系统。系统将研究任务拆分给 planner、searcher、reader、analyzer、critic、writer、validator、debate 和 synthesizer 等 Agent，通过两种 LangGraph `StateGraph` 拓扑生成带证据链的结构化报告。

核心目标：

- 并行执行可独立处理的研究子任务；
- 通过 SSE 实时展示各 Agent 的状态和 token 流；
- 通过 critique、补充检索和报告修复循环控制质量；
- 记录来源、主张、模型使用、成本和审计信息；
- 支持多个研究任务在前后端并发运行且互不干扰。

## 2. 快速开始

- Python 3.13（依赖来自 `deep_research_system/environment.yml`）

### 后端

```bash
cd deep_research_system
python main.py
# 或
uvicorn main:app --reload --port 8000
```

API 默认挂载在 `/api`，交互式文档位于 `http://localhost:8000/docs`。

### 前端

```bash
cd deep_research_system/frontend
npm ci
npm run dev
```

常用检查：

```bash
# deep_research_system/
python -m pytest tests/ -v

# deep_research_system/frontend/
npx vue-tsc --noEmit
npm run build
```

运行前需按 `deep_research_system/.env.example`（若存在于当前检出版本）或配置模型槽位、Redis 和搜索服务所需环境变量。

## 3. 分层架构

```text
Vue 3 UI
  └─ Pinia 多会话 Store
       ├─ REST: 创建、查询、取消、删除任务
       └─ SSE: 每个任务独立 EventSource
                    │
                    ▼
FastAPI (`main.py`, `app/api/`)
  └─ ResearchService
       ├─ 内存中的任务、运行句柄和订阅队列
       ├─ TaskStateStore（Redis 持久化与恢复）
       └─ TopologyRouter
            ├─ HierarchicalTopology ─┐
            └─ DebateTopology ───────┤ 薄委托层
                                     ▼
                         LangGraph GraphRunner (`app/graphs/`)
                            ├─ Agent 调度与并行分支
                            ├─ 质量控制循环
                            └─ GraphContext（每次运行隔离）
                                     │
                                     ▼
                         Agents → Model Pool → LLM API
                            └─ SearchService → Tavily
```

### 3.1 API 层

`deep_research_system/main.py` 创建 FastAPI 应用，并以 `/api` 为前缀挂载 `app/api/routes.py`。研究接口定义于 `app/api/routes_research.py`：

| 方法 | 路径 | 用途 |
|---|---|---|
| `POST` | `/api/research` | 创建后台异步任务并立即返回 |
| `POST` | `/api/research/sync` | 等待任务完成后返回 |
| `GET` | `/api/research` | 列出任务 |
| `GET` | `/api/research/{task_id}` | 查询任务状态与结果 |
| `GET` | `/api/research/{task_id}/stream` | 订阅 SSE；先发送当前 state，之后发送实时事件 |
| `POST` | `/api/research/{task_id}/cancel` | 取消运行中的任务 |
| `DELETE` | `/api/research/{task_id}` | 删除非运行中任务；运行中任务返回 409 |

SSE 在 30 秒无事件时发送 keepalive，并在 `done`、`cancelled` 或 `error` 后结束。

### 3.2 服务与持久化层

`app/services/research_service.py` 的 `ResearchService` 管理完整任务生命周期：

1. `create_task()` 创建 `asyncio.Task` 后立即返回；`create_task_sync()` 则等待执行完成。
2. `_execute()` 为任务创建新的 `ResearchState`，并定义捕获当前 `task_id` 的事件回调。
3. 回调给事件补充 `task_id`，广播到该任务的 SSE 队列，并持久化进度。
4. 任务完成后返回 `report`、`claim_graph`、`metrics` 和 `audit_trail`。
5. `cancel_task()` 取消对应运行句柄；删除运行中任务必须先取消。

`app/services/task_state_store.py` 使用 Redis 保存任务状态与事件，内存中没有任务时作为查询回退。状态和事件分别使用 7 天与 3 天 TTL；服务初始化时会把遗留的 `running` 任务标记为失败。

> 当前内存缓存按用户 query 的 MD5 建键，不包含 depth、budget 等参数。改变缓存语义时应同步调整文档和测试。

## 4. LangGraph 编排

项目确实使用 LangGraph。职责分为两层：

- `app/topology/`：`HierarchicalTopology`、`DebateTopology` 和 `TopologyRouter`。拓扑对象懒加载 graph runner，`execute()` 只委托给 `runner.run()`。
- `app/graphs/`：主要编排实现。`hierarchical_graph.py` 与 `debate_graph.py` 构建并执行 `StateGraph`；`events.py` 提供事件辅助函数；`graph_state.py` 定义图状态。

`factory.py` 与 `nodes.py` 提供另一套可复用节点/工厂模式，目前不是主要执行路径。

### 4.1 层级式拓扑

```text
planner
  → search（按 sub-question 并行）
  → reader（按 sub-question 并行）
  → analyzer
  → critic
      ├─ 信息不足 → supplementary_search → analyzer → critic（最多 1 轮）
      └─ 信息充分
  → writer
  → validator
      ├─ score < 85 → repair_writer_N → validator（最多 2 次修复）
      └─ 通过/达到上限 → END
```

Searcher 和 Reader 通过工厂为每个子问题创建独立 Agent 实例，使用 `asyncio.gather()` 并行运行。子任务事件名遵循 `searcher_{id}`、`reader_{id}` 约定；Debate 并行分支使用动态 `h_{index}`。

### 4.2 辩论式拓扑

```text
planner
  → debate（按 hypothesis 并行）
  → critic
  → synthesizer
  → writer
  → validator
      ├─ score < 85 → repair_writer_N → validator（最多 2 次修复）
      └─ 通过/达到上限 → END
```

并行辩论节点使用动态 `h_{index}` 作为前端可识别的 Agent 名称。

### 4.3 并发安全的 `GraphContext`

`app/graphs/graph_state.py` 定义：

```python
class GraphContext(TypedDict):
    state: ResearchState
    on_event: NotRequired[EventCallback]
    last_validation: NotRequired[dict]
    supplementary_result: NotRequired[dict | None]
    repair_attempt: NotRequired[int]
    supplementary_loop_count: NotRequired[int]
    last_plan_result: NotRequired[dict]
```

每次 `GraphRunner.run()` 都创建新的 context，并把本次任务的 `on_event` 放在其中。节点从参数中的 context 读取回调，而不是读取 runner 的可变实例字段，因此共享 runner 可以安全服务多个并发任务。

`app/graphs/events.py` 中：

- `emit(on_event, event)` 统一发送同步或异步事件；
- `wrap_agent_name(on_event, name)` 为复合/子任务节点替换事件中的 Agent 名称。

不要把当前任务的回调、task ID 或中间结果保存到共享 runner/Agent 的可变实例字段。

## 5. Agent 与模型池

所有 Agent 继承 `app/agents/base.py` 的 `BaseAgent`。一次典型执行包含：

1. Agent 声明 `TaskRequirement`；
2. `FallbackRouter` 按能力、成本和延迟要求选择模型；
3. Prompt loader 渲染 `prompts/{agent}/` 下版本化的 Jinja2 模板；
4. `LLMClient` 使用共享 `httpx.AsyncClient` 流式调用 OpenAI-compatible API；
5. token 通过 `agent_stream_token` 事件发送；
6. `_parse_output()` 从响应中提取 JSON，并发出结构化输出事件。

模型配置采用四槽位环境变量：

- `MODEL_SEARCH_*`：搜索与阅读；
- `MODEL_ANALYSIS_*`：结构化分析；
- `MODEL_REASONING_*`：规划与批判；
- `MODEL_WRITING_*`：报告写作与综合。

模型定义、Agent 角色和拓扑质量参数分别位于：

- `deep_research_system/config/models.yaml`
- `deep_research_system/config/agents.yaml`
- `deep_research_system/config/topology.yaml`

## 6. 核心数据与输出协议

`app/schemas/state.py` 的 `ResearchState` 嵌套在 `GraphContext["state"]` 中。主要字段包括：

- 任务与路由：`task`、`selected_topology`、`writer_template`；
- 中间结果：`plan`、`sub_results`、`debate_results`、`analyses`、`critiques`；
- 证据协议：`source_registry`、`claim_graph`、`claim_audit`、`repair_context`；
- 最终结果：`final_report`；
- 可观测性：`cost_so_far`、`token_usage`、`model_usage`、`audit_trail`、`errors`、`progress`。

`app/schemas/agent_outputs.py` 规定主张类型：

- `factual_claim`
- `analytical_claim`
- `forecast_claim`
- `risk_claim`
- `research_limitation`

Critic finding 的 `resolution_action` 必须是 `blocker`、`downgrade_required`、`limitations_only` 或 `acceptable_uncertainties`。`research_limitation` 不得作为 section 的 `key_claims`。

最终 `done` payload 包含：

```text
report + claim_graph + metrics + audit_trail
```

主要事件类型包括 `stage_start`、`stage_complete`、`agent_model_selected`、`agent_thinking`、`agent_output`、`agent_stream_token`、`subtask_complete`、`report_update`、`done`、`cancelled` 和 `error`。

## 7. 前端多会话架构

`frontend/src/stores/research.ts` 的 Pinia store 不是单任务 store：

```text
sessions: Record<task_id, ResearchSession>
sessionOrder: task_id[]
activeSessionId: string | null
draftSession: ResearchSession | null
```

每个 session 独立保存任务、事件、节点状态、Agent 详情和 loading/subscription 状态。Store 还以 `task_id` 为键分别管理：

- `EventSource`；
- 轮询定时器；
- token buffer 与 50ms flush timer。

因此创建或切换新会话不会停止其他任务。最近激活的真实任务 ID 保存在 localStorage 的 `deep-research:last-active-task-id`；新会话草稿使用 `draft:new`。

关键组件：

- `SessionSidebar.vue`：会话列表、新建、切换和删除；
- `ResearchForm.vue`：查询、任务类型和深度输入；
- `TopologyGraph.vue`：VueFlow 拓扑图，按命名约定动态注入子任务节点；
- `DetailPanel.vue`：展示每个 Agent 的模型、活动、token 流和结构化输出；
- `ReportViewer.vue`：展示最终报告，并通过 `claim_graph` 查询 claim type；
- `utils/export.ts`：Markdown、PDF、Word 导出。

## 8. 一次任务的数据流

1. 前端 `POST /api/research`，获得 `task_id`。
2. Store 创建 session，并连接 `/api/research/{task_id}/stream`。
3. API 先发送当前 `state`，随后发送实时事件。
4. `ResearchService._execute()` 创建本任务的 `ResearchState` 和事件闭包。
5. `TopologyRouter` 选择拓扑；薄拓扑层调用对应 graph runner。
6. Graph 节点运行 Agent，并通过 context 中的回调发送事件。
7. Store 按 `task_id` 路由事件；token 按 Agent 缓冲，每 50ms 合并刷新。
8. `report_update` 更新阶段性报告，`done` 写入最终结果并停止该 session 的 SSE/轮询。
9. 内存数据不可用时，查询接口尝试从 Redis 恢复任务。

## 9. 推荐代码阅读顺序

1. `deep_research_system/main.py`
2. `deep_research_system/app/api/routes_research.py`
3. `deep_research_system/app/services/research_service.py`
4. `deep_research_system/app/topology/router.py`
5. `deep_research_system/app/topology/hierarchical.py`
6. `deep_research_system/app/graphs/graph_state.py`
7. `deep_research_system/app/graphs/hierarchical_graph.py`
8. `deep_research_system/app/agents/base.py`
9. `deep_research_system/app/model_pool/`
10. `deep_research_system/frontend/src/stores/research.ts`
11. `deep_research_system/frontend/src/components/research/TopologyGraph.vue`

理解层级式拓扑后，再阅读 `app/graphs/debate_graph.py` 比较两者差异。

## 10. 扩展指南

### 新增 Agent

1. 在 `app/agents/` 新建 `BaseAgent` 子类并声明 `TaskRequirement`。
2. 在 `prompts/{agent}/` 添加版本化 Jinja2 模板。
3. 在 `config/agents.yaml` 注册角色配置。
4. 在 graph runner 中复用现有事件辅助函数接入节点；并行子任务应使用工厂创建独立实例。
5. 若 Agent 会出现在 UI，更新前端节点命名/布局与详情展示规则。
6. 添加输出 schema、图执行和事件路由测试。

### 新增拓扑

1. 在 `app/graphs/` 构建并编译新的 `StateGraph` runner。
2. 让每次 `run()` 创建独立 `GraphContext`，所有请求级状态都通过 context 传递。
3. 在 `app/topology/` 添加薄委托类。
4. 在 `app/topology/router.py` 注册任务类型路由。
5. 在 `config/topology.yaml` 添加配置，并同步前端拓扑可视化。

### 新增模型

1. 配置对应槽位环境变量/API key。
2. 在 `config/models.yaml` 注册模型、能力和成本/延迟属性。
3. 确认 Agent 的 `TaskRequirement` 能匹配该模型。
4. 为 fallback、key circuit breaker 和不可用场景添加测试。

## 11. 常见注意事项

- 所有 HTTP 研究路由都有 `/api` 前缀。
- `create_task()` 是异步创建，不要在调用方假设返回时报告已经完成。
- 删除运行中任务会返回 409；先取消，再删除。
- 共享 graph runner 不等于共享请求状态；请求状态必须保留在 `GraphContext`。
- 前端 Agent 名称必须与后端事件一致，否则拓扑节点和详情面板无法正确关联。
- 修改报告 schema 时，应同步 Agent prompt、确定性 validator、API 类型和前端渲染。
