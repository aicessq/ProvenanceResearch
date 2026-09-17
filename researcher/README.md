[English](README_EN.md) | **中文**

<div align="center">

# MultiAgentIR

**异构模型协同 Deep Research 系统**

基于 FastAPI + Vue 3 的多 Agent 智能检索分析框架，通过异构模型路由、Agent 角色拆分与可切换拓扑编排，自动完成高质量深度研究报告生成。

[![Python 3.13](https://img.shields.io/badge/Python-3.13-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg)](https://fastapi.tiangolo.com/)
[![Vue 3](https://img.shields.io/badge/Vue-3-4FC08D.svg)](https://vuejs.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

</div>

---

## 系统架构

<div align="center">
  <img src="fig/fig1.png" alt="System Architecture" width="800"/>
</div>

---

## 核心亮点

- **异构模型协同** — 不同 Agent 根据能力需求自动路由到不同模型，低成本模型铺量，强模型把关
- **双拓扑编排** — 行业报告走层级式拓扑（Hierarchical），开放性问题走辩论式拓扑（Debate），由 LangGraph 负责工作流执行
- **并行子任务** — 每个子问题独立实例化 Searcher/Reader，由 LangGraph 节点协调并发执行
- **实时 SSE 流** — 前端通过 Server-Sent Events 实时接收 Agent 思考过程、Token 流、阶段状态
- **多会话并行** — Pinia 按 `task_id` 独立管理多个会话、SSE、轮询和 Token 缓冲，切换会话不会停止其他任务
- **自动修复循环** — Validator 校验报告质量，低于阈值自动触发 Writer 修复（最多 2 次）
- **补充检索循环** — Critic 发现信息不足时自动触发补充搜索 → 重新分析 → 重新审稿
- **配置驱动** — 新增模型、Agent、Prompt、拓扑时尽量不改核心代码，统一 YAML 配置管理

---

## 拓扑编排

### 拓扑 A：Hierarchical（行业报告）

适合有明确结构、强事实依赖的研究任务：

```
        Planner
           ↓
     SubQuestion List
           ↓
 ┌─────────┼─────────┐
 ↓         ↓         ↓
Searcher  Searcher  Searcher   ← 并行执行
 ↓         ↓         ↓
Reader    Reader    Reader      ← 并行执行
 └─────────┼─────────┘
           ↓
        Analyzer
           ↓
        Critic
           ↓              ← 若 needs_more_research，触发补充检索循环
        Writer
           ↓
        Validator         ← 若 score < 85，触发修复循环
           ↓
      Final Report
```

### 拓扑 B：Debate（开放性问题）

适合争议性观点分析、策略选择等非标准答案问题：

```
          Planner
             ↓
       Debate Questions
             ↓
 ┌───────────┼───────────┐
↓           ↓           ↓
h_0         h_1         h_{index}       ← hypotheses 动态并行
↓           ↓           ↓
Evidence    Evidence    Evidence
└───────────┼───────────┘
             ↓
          Critic
             ↓
        Synthesizer
             ↓
          Writer
             ↓
        Validator
             ↓
      Final Research Memo
```

---

## 技术栈

| 层级 | 技术 | 用途 |
|------|------|------|
| **后端** | Python 3.13 / FastAPI | API 服务、SSE 流、OpenAPI 文档 |
| | LangGraph | 工作流编排、分支路由、循环控制 |
| | Pydantic v2 | Schema 校验、配置建模 |
| | httpx / asyncio | 异步 HTTP、底层并发执行 |
| | Redis | 任务状态与事件持久化（含 TTL） |
| | tenacity | 重试、退避、熔断恢复 |
| **前端** | Vue 3 / TypeScript | 响应式 UI、类型安全 |
| | Pinia | 状态管理、SSE 事件路由 |
| | VueFlow | 拓扑图可视化、节点拖拽 |
| | Vite / TailwindCSS | 构建工具、样式 |
| **配置** | YAML / Jinja2 | 模型注册、Agent 配置、Prompt 模板 |

---

## Agent 角色

| Agent | 职责 | 模型需求 | 输出 |
|-------|------|----------|------|
| **Planner** | 任务理解与拆解 | 强推理 | `sub_questions[]` |
| **Searcher** | 查询改写与网页检索 | 联网搜索 | `sources[]` |
| **Reader** | 长文本阅读与证据抽取 | 长上下文 | `evidence[]`, `key_findings[]` |
| **Analyzer** | 跨信源分析与矛盾识别 | 长上下文 | `claim_graph`, `contradictions[]` |
| **Critic** | 批判性审稿与事实校验 | 强推理 | `issues[]`, `needs_more_research` |
| **Writer** | 结构化研究报告生成 | 强写作 | `final_report` |
| **Validator** | 输出 Schema 校验与质量把关 | 轻量校验 | `valid`, `score`, `issues[]` |

---

## 数据流

```
1. 前端 POST /api/research → 获取 task_id
2. 前端打开 SSE 连接 /api/research/{id}/stream
3. 后端 ResearchService._execute() 构造 ResearchState，并调用 LangGraph 编排器
4. LangGraph 节点复用现有 Agent.run() / SearchService / Validator 逻辑
5. 运行时将 LangGraph 节点事件适配为既有 SSE 事件并实时推送到前端
6. 前端 store 路由事件：
   - stage_start/complete → nodeStates
   - agent_stream_token → token buffer (50ms flush)
   - report_update → result.report
   - done → 最终结果
7. ReportViewer 渲染报告，启用导出
```

---

## 快速开始

### 环境要求

- Python 3.13（建议使用仓库提供的 Conda `environment.yml`）
- Node.js 18+
- Redis（用于任务状态与事件持久化；不可用时仅保留进程内数据，不能跨重启恢复）

### 1. 后端启动

```bash
cd deep_research_system

# 创建并激活 Python 3.13 Conda 环境
conda env create -f environment.yml
conda activate multiagent

# 本项目使用 environment.yml 安装依赖；没有 requirements.txt 或 pyproject.toml

# 配置环境变量
cp .env.example .env
# 编辑 .env，至少填写一个模型的 API Key

# 启动服务
python main.py
# 或
uvicorn main:app --reload --port 8000
```

### 2. 前端启动

```bash
cd deep_research_system/frontend

npm ci
npm run dev
```

访问 `http://localhost:3000` 即可使用。

### 3. 快速验证

```bash
# 健康检查
curl http://localhost:8000/api/health

# 发起研究任务
curl -X POST http://localhost:8000/api/research \
  -H "Content-Type: application/json" \
  -d '{"query": "2025年AI Agent市场趋势分析", "task_type": "industry_report", "depth": "quick"}'
```

---

## 项目结构

```
deep_research_system/
├── main.py                  # 后端入口
├── .env                     # 环境变量
├── config/                  # YAML 配置
│   ├── app.yaml             # 应用设置、成本估算
│   ├── models.yaml          # 模型注册表
│   ├── agents.yaml          # Agent 配置
│   └── topology.yaml        # 拓扑设置（最大子问题数、修复循环次数）
├── prompts/                 # Jinja2 提示词模板（版本化管理）
│   ├── planner/v3_hypothesis.zh.j2
│   ├── searcher/v4_query_planner.zh.j2
│   ├── reader/v2_atomic_facts.zh.j2
│   ├── analyzer/v2_claim_graph.zh.j2
│   ├── critic/v2_structured_critique.zh.j2
│   ├── writer/industry_report.zh.j2
│   ├── validator/v2_evidence_check.zh.j2
│   └── debate/*.zh.j2
├── app/
│   ├── api/                 # FastAPI 路由
│   │   ├── routes_research.py   # POST /api/research, GET /api/research/{id}/stream
│   │   └── routes_health.py
│   ├── agents/              # Agent 实现
│   │   ├── base.py          # BaseAgent: run(), _emit(), _parse_output()
│   │   ├── planner.py       # 任务拆解
│   │   ├── searcher.py      # 网页检索
│   │   ├── reader.py        # 证据抽取
│   │   ├── analyzer.py      # 跨信源分析
│   │   ├── critic.py        # 批判性审稿
│   │   ├── writer.py        # 报告生成
│   │   └── validator.py     # 质量校验
│   ├── topology/            # 业务拓扑入口（委托给 LangGraph）
│   │   ├── base.py          # BaseTopology.emit()
│   │   ├── hierarchical.py  # 层级式拓扑入口
│   │   ├── debate.py        # 辩论式拓扑入口
│   │   └── router.py        # 任务类型 → 拓扑路由
│   ├── graphs/              # LangGraph 编排层
│   │   ├── events.py        # LangGraph → SSE 事件适配
│   │   ├── graph_state.py   # GraphContext / ResearchState 桥接
│   │   ├── hierarchical_graph.py
│   │   ├── debate_graph.py
│   │   └── factory.py       # GraphRunner 构建
│   ├── model_pool/          # 模型能力池
│   │   ├── registry.py      # ModelRegistry: 模型配置
│   │   ├── router.py        # FallbackRouter: 能力/成本路由
│   │   ├── key_pool.py      # APIKeyPool: Key 管理
│   │   └── client.py        # LLMClient: 流式调用
│   ├── schemas/             # Pydantic 数据模型
│   │   ├── state.py         # ResearchState: 全局状态
│   │   ├── task.py          # TaskSpec, TaskRequirement
│   │   └── agent_outputs.py # ClaimType, ResolutionAction
│   ├── services/            # 业务服务
│   │   ├── research_service.py  # 任务生命周期、SSE pub/sub
│   │   ├── search_service.py    # Tavily API 封装
│   │   └── trace_service.py     # 审计日志
│   └── core/                # 配置/日志/中间件/安全
├── frontend/                # Vue 3 前端
│   ├── src/
│   │   ├── stores/research.ts   # Pinia store: SSE 事件路由
│   │   ├── views/ResearchView.vue
│   │   └── components/research/
│   │       ├── TopologyGraph.vue   # VueFlow 拓扑图
│   │       ├── AgentNode.vue       # 节点渲染
│   │       ├── DetailPanel.vue     # Agent 输出详情
│   │       ├── ReportViewer.vue    # 报告渲染
│   │       └── ProgressBar.vue     # 阶段进度
│   └── package.json
├── tests/                   # 测试用例
└── output/reports/          # 生成的报告
```

---

## 模型配置

系统支持异构模型接入，通过 `config/models.yaml` 配置。环境变量配置见 `.env.example`：

```ini
# 槽位 1: 搜索/阅读用模型（低成本，支持长上下文）
MODEL_SEARCH_NAME=deepseek-chat
MODEL_SEARCH_API_KEY=sk-your-key
MODEL_SEARCH_API_BASE=https://api.deepseek.com

# 槽位 2: 分析用模型
MODEL_ANALYSIS_NAME=deepseek-chat
...

# 槽位 3: 规划/审稿用模型（强推理能力）
MODEL_REASONING_NAME=deepseek-reasoner
...

# 槽位 4: 写作用模型（强写作能力）
MODEL_WRITING_NAME=deepseek-chat
...
```

所有模型均通过 API 调用，兼容 OpenAI 接口标准，支持国产模型 API。

---

## SSE 事件类型

子任务事件名遵循 `searcher_{id}`、`reader_{id}` 约定；Debate 并行分支使用动态 `h_{index}`。

| 事件类型 | 用途 |
|----------|------|
| `stage_start` | Agent 阶段开始 |
| `stage_complete` | Agent 阶段完成 |
| `agent_model_selected` | 模型选择通知 |
| `agent_thinking` | 思考过程 |
| `agent_stream_token` | Token 流（前端 50ms buffer） |
| `agent_output` | Agent 输出结果 |
| `subtask_complete` | 子任务完成 |
| `report_update` | 中间报告推送 |
| `done` | 最终结果 |
| `error` | 错误 |

---

## License

MIT
