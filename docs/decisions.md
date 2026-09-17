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

## 2026-09-17 测试基线首次实测：两套测试全绿

- 决定：把两个子系统的测试与前端构建**首次实际跑通并记录为基线**，结果写入新建的 `docs/testing.md`；此后每轮改动以该文件的命令为准，结论变化即回写。
- 结果：`knowledge_engine` → 96 passed / 34 deselected（integration 默认排除）；`researcher` → 47 passed；两套前端 `npm ci && npm run build` 均通过；gitleaks v8.30.1 扫描无泄漏。**失败分类：0 个代码失败、0 个环境失败。**
- 理由：P1/P2 的验收是"原测试全绿"，此前只有静态计数（34 模块 / 约 130 测试、8 模块 / 47 测试），从未实际运行；不实测就无法把"测试是否还绿"当作后续 AI 改动的裁判。
- 附带发现：`researcher` 测试在没有 `.env` 的临时副本下同样 47 passed，故 CI 环境等价性成立；`knowledge_engine` 下本就没有 `.env`。integration 测试（34 个）需要真实 PG/Redis/Qdrant，因本机 Docker 守护进程未启动而未运行。

## 2026-09-17 CI 范围：只做"跑既有测试"与"挡密钥"

- 决定：PR 门禁只包含四项——`knowledge_engine` 单元测试、`researcher` 测试、两套前端构建、gitleaks 密钥扫描。
- 明确不做：ruff / mypy / 格式门禁；integration 测试与 service container；OpenAPI 兼容性检查（属 P3，跟随 `/api/v1` 契约冻结）。
- 理由：给两个旧项目加 lint 要么大面积红、要么逼出一份例外清单，两者都等于"顺手重构"，直接违反迁移期纪律。integration 需要 Docker，本机守护进程尚不满足，先作为 PR 外任务。前端构建之所以能进门禁，是因为已在本机验证通过，而不是凭预期。
- 实现取舍：`researcher` 没有 pyproject/requirements，`environment.yml` 是唯一依赖清单，CI 从其 pip 段提取固定版本安装（不改该文件、不用 conda 拖慢 CI）；gitleaks 采用官方 action 而非自建下载步骤——沙箱网络无法验证 Linux 资产名，把平台解析交给 action 更可控。注意 organization 拥有的仓库需要 `GITLEAKS_LICENSE`，个人仓库不需要。

## 2026-09-17 本机 knowledge_engine 测试环境复用系统包

- 决定：本机跑 `knowledge_engine` 测试用的 `.venv` 以 `python -m venv --system-site-packages` 创建，torch / transformers / sentence-transformers 复用既有 conda 环境，其余依赖照常安装。
- 理由：沙箱内 torch 的 127MB wheel 下载卡死（连续 5 分钟零字节到达，`--timeout 30` 亦无法中止），而 `test_reranker.py` 与 `reranker.py` 都在模块顶层 `import torch`，缺它连测试收集都会失败。
- 代价与对冲：该环境**不是干净安装**，"命令可复现"因此被削弱。对冲手段是用 AST 静态核对代码与测试中的 14 个第三方顶层导入全部在 `pyproject.toml` 中声明，排除被继承环境掩盖的隐藏依赖；CI 仍走干净的 `pip install -e ".[test]"`。
- 待办：网络恢复后应在干净 venv 中复跑一次以完全消除该不确定性。

## 2026-09-17 用 docs/roadmap.md 承载 P0–P5 与逐阶段验收

- 决定：新建 `docs/roadmap.md` 定义 P0、基线轮、P1–P5 的目标与验收，并显式说明它与 `knowledge_engine` 自带 Phase 0–10 是两套无关编号；根 `AGENTS.md` 与 `README.md` 的引用指向该文件。
- 理由：根 `AGENTS.md` 要求"见各阶段'验收'行"，但仓库里此前只有旧 `knowledge_engine` 的 Phase 0–5，导致"未达标不进入下一阶段"这条纪律没有可解析的目标。
- 同时补齐：根 `.env.example`（此前 README 要求 `cp .env.example .env` 但文件不存在，安装路径是断的）。
