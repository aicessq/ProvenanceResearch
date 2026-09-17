# 设计决策记录

> 规则：任何设计决策（保留了什么、改了什么、为什么）追加写入本文件，每条带日期与理由。

## 2026-09-17 仓库骨架与固定目录

- 决定：新仓库固定六目录——`knowledge_engine/`（RAG_sec 归宿）、`researcher/`（MultiAgentIR_LangGraph 归宿）、`frontend/`、`eval/`、`docs/`、`tests_bridge/`。
- 理由：先固定"归宿"与契约，避免两份代码继续各自漂移；目录名即职责边界。
- 验收：六目录存在；`docs/design.md` 五节 + 非目标齐。

## 2026-09-17 搬运方式：复制而非移动，排除机械垃圾

- 决定：`rsync` 复制；源项目留在 `/Users/zed/MyProject/ProvenanceResearch` 原样不动。
- 排除：`.git/`、`node_modules/`、`.claude/worktrees/`、`.pytest_cache/`、`__pycache__/`、`*.pyc`、`.DS_Store`。
- 保留：全部源码、配置模板（`.env.example`）、文档、前端（RAG_sec 自带 `frontend/` 随项目保留在 `knowledge_engine/` 内；MultiAgentIR 的 `deep_research_system/frontend/` 同理）。
- 改了什么：**零代码改动**（本轮只搬运）。
- 未迁入：两边 git 历史（RAG_sec 11 commit、MultiAgentIR 1 commit）——历史价值有限，仍以原仓库为准；`.claude/worktrees` 属工具残留，不迁。
- 验证：搬后逐文件 sha256 比对为空 diff（RAG_sec 222 个文件、MultiAgentIR 189 个文件）。

## 2026-09-17 环境变量契约：统一 LLM_* 三件套

- 决定：模型统一 `LLM_MODEL` / `LLM_API_KEY` / `LLM_BASE_URL`（OpenAI 兼容）；Embedding 迁移期沿用本地句向量 `EMBEDDING_MODEL_PATH` / `EMBEDDING_VECTOR_SIZE`；Web 搜索 `TAVILY_API_KEY`；基础设施沿用 RAG_sec 命名 `POSTGRES_*` / `REDIS_*` / `QDRANT_*`。
- 理由：合并后只需要一个生成模型；MultiAgentIR 的四槽位（`MODEL_SEARCH/ANALYSIS/REASONING/WRITING_*`）对单 Reader 管线属冗余。RAG_sec 已预留 `LLM_API_KEY` / `LLM_BASE_URL`，可零摩擦复用。
- 影响（下一轮）：researcher 侧读取层改为适配此契约；配置一律经 `.env` 注入，代码内禁止硬编码。

## 2026-09-17 docker-compose：只含基础设施三件

- 决定：`postgres:16` + `redis:7` + `qdrant`（健康检查 + 命名卷），容器名 `ra-*`；不含应用服务。
- 理由：当前不存在两个项目之上的统一入口，提前加 app 服务会制造"假集成点"；模型与 Tavily 变量先以 `.env.example` 作为契约存在。
- 备注：本机未安装 docker，本轮 compose 只做 YAML 语法与结构校验；端口/凭据均可由 `.env` 覆盖，与 cybersec-* 旧栈同跑时需改端口。
- 后续：迁移接线完成后在本文件追加 `backend` / `worker` / `researcher` 服务。

## 2026-09-17 融合与闸门的默认常量（可调）

- 决定：RRF `k=60`；来源权重 `w(kb_chunk)=1.0` / `w(web)=0.7`；融合截断 top-8；引用闸门重试上限 1 次；"私库优先"取排序偏向而非硬屏蔽。
- 理由：先给可实现的确定默认值，交由三组消融评测验证；任何调整必须回写本文件。

## 2026-09-17 非目标确认

- 决定：辩论拓扑、多知识库泛化、代码/表格解析、前缀 UI 一律不实现（详见 `docs/design.md` "不做的范围"）。
- 理由：控制迁移面，保证"骨架 → 迁移 → 评测"节奏，防止范围蔓延。

## 2026-09-17 .gitignore 与首次提交基线

- 决定：新仓库 git 不跟踪构建产物与本地工具状态——`frontend/dist/`、`*.tsbuildinfo`、`.claude/settings.local.json`；文件保留在磁盘上，只是不进 git。
- 依据（已逐条核对上游跟踪情况）：上游仓库把 `node_modules`（RAG_sec，2366 文件）、`.claude/worktrees`（MultiAgentIR，约 12 万文件）、`frontend/dist`（42 文件）、`.DS_Store` 也提交进了 git，属误提交而非有意策略；新仓库按"排除机械垃圾"的约定不再延续。
- 保留：`knowledge_engine/.manual-api-work/*` 与 `researcher/.trae/specs/*`（上游跟踪的业务文本与规格文档）照常进仓库。
- 基线：首次提交作为骨架基线，后续每轮改动从它算 diff。

## 2026-09-17 本地凭证默认不进入 Git

- 决定：根 `.gitignore` 统一忽略任意层级的真实 `.env` 及其本地变体、`researcher` 的运行时 `data/config.db`、私钥/证书密钥库和常见云凭证文件；显式保留 `.env.example` 与 `.env.*.example` 配置模板。
- 理由：项目面向本地自托管，用户会配置 LLM、Tavily 和基础设施凭证；`researcher/deep_research_system/data/config.db` 的 `model_slots.api_key` 字段也会存储运行时密钥。凭证文件必须默认拒绝提交，而模板仍需进入版本库以支持安装。
- 验收：真实 `.env` 与 `data/config.db` 能被 `git check-ignore` 命中；三份现有 `.env.example` 不被忽略；Git 索引中不存在敏感命名文件；文件名级凭证扫描无额外私钥或凭证文件。
