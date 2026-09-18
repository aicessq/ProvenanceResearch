# 测试命令与已记录的基线

本文件是根 `AGENTS.md`「每轮改动后必须运行对应测试」的操作依据：**命令 + 已记录的真实结果**。
每次跑的结论若与上次不同，回写本文件（并在 `docs/decisions.md` 记录原因）。

## 快速对照

| 目标 | 命令（在下列目录内执行） | 最近一次结果 |
| --- | --- | --- |
| knowledge_engine 单元测试 | `pytest`（目录 `knowledge_engine/`） | 96 passed, 34 deselected |
| knowledge_engine 集成测试 | `pytest -m integration`（同上，需 PG/Redis/Qdrant） | 未运行（本机无 Docker 守护进程） |
| researcher 测试 | `python -m pytest tests/ -q`（目录 `researcher/deep_research_system/`） | 47 passed |
| knowledge_engine 前端构建 | `npm ci && npm run build`（目录 `knowledge_engine/frontend/`） | 通过 |
| researcher 前端构建 | `npm ci && npm run build`（目录 `researcher/deep_research_system/frontend/`） | 通过 |
| 密钥扫描 | `gitleaks git .`（仓库根） | no leaks found |
| 评测语料完整性 | `python eval/corpus/check_corpus.py`（仓库根） | 通过（28 条 / 21 入库 / 7 仓库外） |
| 人工题集校验 | `python eval/questions/validate_questions.py`（仓库根） | 通过（56 题、配额达标、verified=0） |
| 仓库契约 | `python scripts/check_repo_contracts.py`（仓库根） | 通过（12 份自撰文档、9 条敏感路径、5 类云能力） |

后三项即 CI 的 `repo-contracts` 作业，纯标准库、不联网、不需要任何 secret；负向测试已验证它们会失败（故意把 arXiv 条目标为 `in_repo=true`，脚本报出"不可再分发内容将被发布"）。

## CI 实际运行记录

| 运行 | 提交 | 结论 | 说明 |
| --- | --- | --- | --- |
| #1 | `764c0ef` | 失败（2/6） | 首次运行即暴露两个真实问题：题集校验把"资产本就不发布"误判为缺失；gitleaks action 自带二进制版本较旧、忽略允许清单 |
| #2 | `8fa871a` | **成功（6/6）** | 总耗时 2.2 分钟；见 [run #2](https://github.com/aicessq/ProvenanceResearch/actions/runs/35361823425) |

> 教训：**本地绿 ≠ CI 绿**。两次失败的根源都是"仓库里没有的东西"——被 gitignore 的 arXiv 资产、action 自带二进制的版本。这正是首次运行 CI 的价值。

## 基线记录（2026-09-17，基线轮）

### knowledge_engine

- **命令**：`cd knowledge_engine && pytest`
- **结果**：`96 passed, 34 deselected, 5 warnings in 3.65s`
- **失败分类**：无。0 个代码失败、0 个环境失败。
- **默认划分**：由 `pyproject.toml` 的 `addopts = "-m 'not integration'"` 决定，34 个 integration 测试默认被排除。96 + 34 = 130，与静态计数一致。
- **环境**：Python 3.12.13；pytest 9.1.1；sqlalchemy 2.0.54 / alembic 1.20.0 / qdrant-client 1.19.1 / redis 8.1.0 / celery 5.6.3 / psycopg2-binary 2.9.13 / PyMuPDF 1.28.2 / torch 2.10.0 / sentence-transformers 5.3.0 / transformers 5.3.0 / fastapi 0.135.1 / pydantic 2.12.5。
- **无需 `.env`**：`knowledge_engine/` 下不存在 `.env`，本次运行即无 `.env` 状态，与 CI 等价。
- **环境注意**：本机 `.venv` 是 `python -m venv --system-site-packages` 建的，torch 等重依赖复用自既有 conda 环境——因为沙箱内 torch 的 127MB wheel 下载卡死（连续 5 分钟零字节到达）。为排除"本地绿是假绿"，已用 AST 静态核对：代码与测试中 14 个第三方顶层导入（alembic / celery / fastapi / fitz / httpx / pydantic / pydantic_settings / pytest / qdrant_client / redis / sentence_transformers / sqlalchemy / torch / transformers）**全部**在 `pyproject.toml` 中声明，不存在被继承环境掩盖的隐藏依赖。CI 走干净的 `pip install -e ".[test]"`。

### researcher

- **命令**：`cd researcher/deep_research_system && python -m pytest tests/ -q`
- **结果**：`47 passed in 0.39s`（`-v` 下 47 项全 PASSED）
- **失败分类**：无。
- **环境**：Conda 环境 `multiagent`，Python 3.13.13，pytest 9.0.3，与 `environment.yml` 声明一致。
- **无需 `.env`（已验证）**：把 `deep_research_system/` 复制到临时目录并排除 `.env` 后重跑，同样 47 passed。CI 中不会有 `.env`，因此 CI 等价性成立。
- **无 integration 通道**：该项目没有 integration marker，测试全部走 stub/monkeypatch，不连真实 Redis/Tavily/LLM。

### 前端构建

- **knowledge_engine/frontend**：`npm ci && npm run build`（即 `tsc -b && vite build`）通过，产物 49 modules。
- **researcher/deep_research_system/frontend**：`npm ci && npm run build`（即 `vue-tsc && vite build`）通过，1703 modules。
- **本机工具链**：node v26.8.1 / npm 11.19.0；CI 用 node 22。两套 `package.json` 都没有声明 `engines` 约束。

### 密钥扫描

- **工具**：gitleaks v8.30.1（`gitleaks git .`，扫描 2 个提交、约 2.10 MB）
- **结果**：`no leaks found`

## 尚未运行的部分

- **knowledge_engine integration 测试（34 个）**：需要真实 PostgreSQL / Redis / Qdrant。本机 Docker CLI 已装（29.8.0）但守护进程未启动，故未运行。`Docker` 就位后按 `pytest -m integration` 补齐，并按 `docs/roadmap.md` 把它加入 main/定时任务而非 PR 门禁。
- **端到端链路**：`researcher` 与 `knowledge_engine` 之间尚无桥接，无可测的跨组件行为；相关测试在 P3 由 `tests_bridge/` 建立。

## 相关

- 阶段划分与验收：`docs/roadmap.md`
- 目标设计与云模型/多模态契约：`docs/design.md`
- CI 配置：`.github/workflows/ci.yml`

## 2026-09-18 规格重冻结后的基线解释

本轮只修改规划、配置模板与约束文档，没有调用真实云服务，也没有把旧应用改成 Agentic RAG。以下结论必须区分：

- `knowledge_engine` 的 `96 passed, 34 deselected` 与 `researcher` 的 `47 passed` 是**迁移回归基线**，不是云端 embedding/OCR/vision 或 Agentic 工具协议验收。
- 本机 knowledge_engine 测试复用了既有 conda 环境的 torch/transformers/sentence-transformers；这是历史测试环境事实。P3a 的生产验收要求干净目标环境不加载本地模型权重，并以 fake/recorded Cloud Model Adapter 契约测试替代真实云调用。
- 既有 `knowledge_engine` integration 测试和真实 GitHub PR CI 仍是未完成项；文档更新不改变其状态。
- 规格重冻结后新增的验收包括 Agent tool trace/预算/停止、Tavily+arXiv 来源、PDF/OCR/vision 的页/区域/资产 provenance、云模型身份/索引迁移、成本/延迟/失败隔离与拒答安全样例；这些测试在 P3/P4 分阶段加入，不能用本表旧绿灯代替。
- AST 导入声明核对和无 `.env` 状态不能证明干净安装、平台或版本兼容；前述历史记录中的“CI 等价”表述只代表当时的配置假设，不作为真实 CI 全绿证明。

### 本轮实际回归结果（2026-09-18）

| 范围 | 实际命令 | 结果 |
| --- | --- | --- |
| knowledge_engine | 从仓库根执行 `knowledge_engine/.venv/bin/python -m pytest knowledge_engine/backend/tests -c knowledge_engine/pyproject.toml -q` | `96 passed, 34 deselected, 6 warnings in 3.82s` |
| researcher | 在 `researcher/deep_research_system/` 执行 `/Users/zed/anaconda3/envs/multiagent/bin/python -m pytest tests/ -q` | `47 passed in 0.38s` |

仍使用原有本机环境，本轮不安装依赖；knowledge_engine 的警告为已有 PyMuPDF SWIG deprecation 与 Qdrant 客户端版本探测警告，没有测试失败。未运行 34 个 integration、真实云 smoke 或 GitHub PR CI；旧前端未改动，未重复构建。文档/根模板的变量唯一性、各云能力字段与空 API key、出站开关默认 false/授权映射默认空（仅静态模板检查，不证明运行时阻断，实际行为待 P3a/P5 验收）、每阶段前置/验收、Markdown 链接和围栏、历史决策只追加、改动仅文档契约均以断言检查。`git diff --check` 通过，gitleaks v8.30.1 对本轮改动文件的目录扫描为 `no leaks found`。
