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

## 2026-10-10 P2.5 阶段回归结果

| 范围 | 实际命令 | 结果 |
| --- | --- | --- |
| knowledge_engine | 从仓库根执行 `knowledge_engine/.venv/bin/python -m pytest knowledge_engine/backend/tests -c knowledge_engine/pyproject.toml -q` | `98 passed, 34 deselected` |
| researcher | 在 `researcher/deep_research_system/` 执行 `/Users/zed/anaconda3/envs/multiagent/bin/python -m pytest tests/ -q` | `74 passed` |
| 仓库契约 | `python3 scripts/check_repo_contracts.py`（仓库根） | 通过（13 份自撰文档、9 条敏感路径、5 类云能力） |
| 评测语料完整性 | `python3 eval/corpus/check_corpus.py` | 通过 |
| 人工题集校验 | `python3 eval/questions/validate_questions.py` | 通过 |

计数变化说明：KE 96 → 98 是 P2.5-0.2 测试迁移净增（`test_answer_generator` 由 2 例改写为 4 例：原第 2 例断言的本地抽取回退正是被删除的 fake success，详见 decisions 2026-10-10）；researcher 47 → 74 为 P2.5 三项新增（0.1 端点防护 18 例、0.2 搜索服务 3 例、0.3 key 绑定 6 例），原有 47 例零改动全绿。34 个 integration、真实云 smoke、前端构建本轮未触碰（前端零改动）。

## 2026-10-10 P3a（providers 适配层）测试基线

| 范围 | 实际命令 | 结果 |
| --- | --- | --- |
| providers 契约测试 | 仓库根 `knowledge_engine/.venv/bin/python -m pytest providers/tests/ -q` | `25 passed` |
| knowledge_engine | 同上 venv，`-m pytest knowledge_engine/backend/tests -c knowledge_engine/pyproject.toml -q` | `98 passed, 34 deselected`（零改动，回归确认） |
| researcher | `researcher/deep_research_system/` 内 conda multiagent `python -m pytest tests/ -q` | `74 passed`（零改动，回归确认） |
| 仓库契约 | `python3 scripts/check_repo_contracts.py` | 通过 |

providers 为新增顶层包（纯 httpx+pytest、无凭证、不联网，fake/recorded 响应）；CI 新增 `providers-tests` 作业（httpx==0.28.1、pytest==9.1.1 钉版）。真实云 smoke 照旧不进普通 PR。providers 测试建议用带 httpx 的任意 3.12+ 环境；KE venv 因复用 torch 环境跑它没有额外成本。

## 2026-10-10 P3c-text（Evidence/工具文本链路）测试基线

| 范围 | 实际命令 | 结果 |
| --- | --- | --- |
| evidence+tools+tests_bridge | 仓库根 `knowledge_engine/.venv/bin/python -m pytest evidence/tests tools/tests tests_bridge -q` | `46 passed` |
| providers（P3a 回归） | 同上 venv，`-m pytest providers/tests/ -q` | `25 passed` |
| knowledge_engine | 同上 venv，`-m pytest knowledge_engine/backend/tests -c knowledge_engine/pyproject.toml -q` | `98 passed, 34 deselected`（零改动） |
| researcher | `researcher/deep_research_system/` 内 conda multiagent `python -m pytest tests/ -q` | `74 passed`（零改动） |

evidence/tools 为新增顶层包（依赖仅 httpx+pytest，fake/recorded 响应，无凭证不联网）；CI 的 providers 作业扩为 `providers/tests/ evidence/tests/ tools/tests/ tests_bridge/` 四目录（71 例）。未跑 34 个 integration、真实云 smoke、前端构建（前端零改动）。

## 2026-10-10 P3d（Agent Loop/Reader/引用闸门）测试基线

| 范围 | 实际命令 | 结果 |
| --- | --- | --- |
| agent（P3d 核心） | 仓库根 `knowledge_engine/.venv/bin/python -m pytest agent/tests -q` | `24 passed` |
| 四新包合计 | 同上 venv，`-m pytest providers/tests evidence/tests tools/tests agent/tests tests_bridge -q` | `95 passed` |
| knowledge_engine | 同上 venv，`-m pytest knowledge_engine/backend/tests -c knowledge_engine/pyproject.toml -q` | `98 passed, 34 deselected`（零改动） |
| researcher | `researcher/deep_research_system/` 内 conda multiagent `python -m pytest tests/ -q` | `74 passed`（零改动） |

agent 为新增顶层包（依赖仅标准库+已有 evidence/tools，fake LLM 驱动真实 loop/executor/store）；CI 的 providers 作业现跑五目录（95 例）。SSE/HTTP/Redis 未做（P3d 后续小步），34 个 integration 与真实云 smoke 照旧未跑。

## 2026-10-10 P3d 后半（SSE v1 + /api/v1 任务接口）测试基线

| 范围 | 实际命令 | 结果 |
| --- | --- | --- |
| 四新包+bridge（含 agent 事件 sink） | 仓库根 `knowledge_engine/.venv/bin/python -m pytest providers/tests evidence/tests tools/tests agent/tests tests_bridge -q` | `100 passed` |
| 同上（conda multiagent / Python 3.13 复核） | 仓库根 `…/multiagent/bin/python3 -m pytest agent/tests providers/tests evidence/tests tools/tests tests_bridge/ -q` | `100 passed` |
| researcher（SSE v1 20 + agentic 桥 10 + /api/v1 9 新增） | `researcher/deep_research_system/` 内 conda multiagent `python -m pytest tests/ -q` | `113 passed` |
| knowledge_engine | 从仓库根执行 `knowledge_engine/.venv/bin/python -m pytest knowledge_engine/backend/tests -c knowledge_engine/pyproject.toml -q` | `98 passed, 34 deselected`（零改动，回归确认） |

计数变化：新契约 95 → 100（agent 增事件 sink 5 例）；researcher 74 → 113（+39：SSE v1 语义 20 例——同一套测试跑内存与 fake-Redis 两个后端、agentic 桥 10 例、/api/v1 HTTP 契约 9 例）。SSE 语义覆盖顺序、终态唯一、完成订阅竞态、Last-Event-ID 重连回放、Redis 故障降级；HTTP 层覆盖 problem+json、旧接口错误形状逐字回归与 OpenAPI 路径检查。全部 fake/recorded（fake LLM + MockTransport + fake Redis 命令），无凭证不联网；34 个 integration、真实云 smoke、前端构建照旧未跑。CI 两套既有作业命令不变即覆盖新测试（researcher 作业现 113 例；providers 作业五目录现 100 例）。

## 2026-10-11 P4 第一轮 baseline（冻结件 + runner + 指标）测试基线

| 范围 | 实际命令 | 结果 |
| --- | --- | --- |
| 四新包+bridge（含 P4 14 例） | 仓库根 `knowledge_engine/.venv/bin/python -m pytest providers/tests evidence/tests tools/tests agent/tests tests_bridge -q` | `115 passed` |
| knowledge_engine | 同上 venv，`-m pytest knowledge_engine/backend/tests -c knowledge_engine/pyproject.toml -q` | `98 passed, 34 deselected`（零改动，回归确认） |
| researcher | `researcher/deep_research_system/` 内 conda multiagent `python -m pytest tests/ -q` | `113 passed`（零改动，回归确认） |
| runner 机械自检 | 仓库根 `knowledge_engine/.venv/bin/python eval/runner.py --mode fake --out eval/results/` | 三条件跑通、safety=PASS（报告标 mode=fake、not_a_conclusion=true） |
| 仓库契约 | `python3 scripts/check_repo_contracts.py` | 通过（13 份自撰文档、9 条敏感路径、5 类云能力） |

计数变化：新契约 100 → 115（agent +1 空 claims 拒答、tests_bridge +14 P4 机械验收）。P4 fake 自检的机械信号（非结论）：A/B/C recall@10 均 0.7059、MRR≈0.637–0.643、引用准确率 0.6429、安全样例 5/5 拒答。**live 正式跑分未执行**：缺 DEEPSEEK_API_KEY/TAVILY_API_KEY，runner live 模式按 AGENTS.md 显式失败拒绝降级；34 个 integration 与前端构建照旧未跑。`eval/results/` 为生成物已入 .gitignore。

## 2026-10-11 P5 第一版（统一前端三栏 + 联调）测试基线

| 范围 | 实际命令 | 结果 |
| --- | --- | --- |
| 统一前端构建 | `cd frontend && npm install && npm run build`（vue-tsc --noEmit + vite build） | 通过（39 模块，产物 85.9 kB JS + 9.4 kB CSS） |
| 浏览器联调 | `scripts/ui_smoke_server.py`（FAKE 运行时）+ `npm run dev` + 浏览器实测 | 三栏渲染 ✓、创建任务→SSE 时间线实时→回答+引用芯片→点芯片高亮 gold 证据卡（含页码/原文）✓、任务切换器/删除按钮 ✓ |
| 四新包+bridge | 仓库根 `knowledge_engine/.venv/bin/python -m pytest providers/tests evidence/tests tools/tests agent/tests tests_bridge -q` | `115 passed`（零改动，回归确认） |
| researcher | `researcher/deep_research_system/` 内 conda multiagent `python -m pytest tests/ -q` | `113 passed`（含 meta 去重修复后回归） |

联调修复记录：时间线曾出现两条 meta（服务带预算的 meta 与 loop trace 只有问题文本的 meta 重复）——`_forward` 现在跳过 loop 的 meta/done（终态由服务统一发）。联调截图已随浏览器交付页保留；CI frontend-build 矩阵加入 `frontend/`（三套前端并行构建，旧两套在替代验收后移除）。FAKE 冒烟服务器明确标注非生产入口、产出非结论（AGENTS.md 约束不破）。

## 2026-10-11 P5 云配置面（加密存储 + 出站授权）测试基线

| 范围 | 实际命令 | 结果 |
| --- | --- | --- |
| researcher（含云配置 12 例） | `researcher/deep_research_system/` 内 conda multiagent `python -m pytest tests/ -q` | `125 passed`（+12：SecretVault 3、配置服务 4、出站门 2、API 3） |
| 四新包+bridge | 仓库根 KE venv `-m pytest providers/tests evidence/tests tools/tests agent/tests tests_bridge -q` | `115 passed`（零改动） |
| 统一前端构建 | `cd frontend && npm run build` | 通过（43 模块） |
| 浏览器联调 | 冒烟后端 + 设置面板实测 | 五能力表单/密钥只写不读/主密钥缺失警告/出站授权默认拒绝（cloud_upload_not_authorized）+ 指纹表/主密钥轮换区 ✓ |

验证的行为（P5 验收项）：凭证 Fernet 加密落盘且 GET/视图不回显（断言明文不在响应与密文文件）；CONFIG_ENCRYPTION_KEY 缺失/弱/格式错拒绝保存、不回退明文；轮换失败保留旧密文、成功后新钥可解；校验失败保留旧值、删除覆盖恢复环境值；provider/endpoint/model 变更使旧出站授权失效（approval_stale_config_changed）；凭证不等于授权（live 探测需 confirm_fingerprint 显式确认）。依赖变更：researcher 环境新增 `cryptography==44.0.0`（environment.yml + 本机 conda multiagent，凭证加密唯一正当选择）。

## 2026-10-11 P3b（多模态入库：OCR/vision + 流水线）测试基线

| 范围 | 实际命令 | 结果 |
| --- | --- | --- |
| 四新包+bridge+ingest | 仓库根 KE venv `-m pytest providers/tests evidence/tests tools/tests agent/tests ingest/tests tests_bridge -q` | `128 passed`（+13：providers OCR/vision 真实适配器 5、ingest 流水线 7、溯源 bridge 1） |
| knowledge_engine | KE venv 原命令 | `98 passed`（零改动，回归确认） |
| researcher | multiagent 原命令 | `125 passed`（零改动，回归确认） |

P3b 验收覆盖（fixture 全合成、fake/recorded、无凭证）：文本层页不再 OCR（不重复）；OCR blocks/bbox/阅读顺序/置信度进 Evidence（像素坐标归一化 0–1，无置信度不伪造）；OCR 失败→vision 兜底且图内文字/可观察/推断分开标注（推断不回填 raw_text）；混合文档必需页 OCR+vision 双失败 → 不发布"完整"版本 + 失败页原因显式报告，其他页不受拖垮；非必需页失败仍可发布但必须报告；rotation/asset hash/图注-资产关联从 parser 保留到 Evidence 与 citation_id（同身份重登记同 id）；低置信度标 low_quality 如实记录。真实适配器契约：百度 OCR（token 缓存/六分类/缺配置显式失败）、OpenAI 兼容 VLM（https-only/结构化输出/非法输出拒绝）。**未覆盖**（记录在 decisions）：Celery 心跳/租约 fencing 与真实 KE 上传→worker→index 集成（需 Docker/PG/Redis/Qdrant 基建与 P1/P2 迁移）、OCR/vision 实际质量分层（P4）。

## 2026-10-11 硬化轮（JWT/限流/观测/Compose）测试基线

| 范围 | 实际命令 | 结果 |
| --- | --- | --- |
| researcher（含硬化 7 例） | multiagent `python -m pytest tests/ -q` | `132 passed`（+7：认证 4、限流 2、指标 1） |
| 四新包+bridge+ingest | KE venv 六目录 | `128 passed`（零改动） |
| knowledge_engine | KE venv 原命令 | `98 passed, 34 deselected`（零改动） |
| 统一前端构建 | `cd frontend && npm run build`（含登录层） | 通过（43 模块） |
| Compose 静态校验 | `cp .env.example .env && docker compose config -q` | 通过（六服务编排合法） |
| 仓库契约 | `python3 scripts/check_repo_contracts.py` | 通过（README 换 Portfolio 描述后链接/契约不回归） |

硬化验收逐项：未认证请求 401（auth_required/token_invalid）✓ 测试；弱/缺主密钥 503 auth_not_configured 不放行 ✓ 测试；限流 429+Retry-After（query/ingest/default 分桶、分客户端）✓ 测试；`/metrics`（http/auth_failures/rate_limited/task_terminal 计数）与 LOG_FORMAT=json 结构化日志 ✓；Compose 全栈**起栈冒烟未跑**（本机无 Docker 守护进程，静态校验通过；需用户 `docker compose up` 后按 README 冒烟）；三个失败案例演示路径写入 README（无证据拒答/来源冲突/provider failure），其中前两者已有自动化断言（refusal 测试、版本对照语料+证据并列），provider failure 由 P2.5/P3a 契约测试覆盖。JWT 依赖 pyjwt==2.10.1（装前已说明）。

## 2026-10-11 硬化轮补丁：出站门接入运行时构建点

| 范围 | 实际命令 | 结果 |
| --- | --- | --- |
| researcher（+2：来源出站授权、运行时出站执法） | multiagent `python -m pytest tests/ -q` | `134 passed` |
| 四新包+bridge+ingest（P4 live 门含出站授权） | KE venv 六目录 | `128 passed` |
| 仓库契约 | `python3 scripts/check_repo_contracts.py` | 通过 |

行为变化：生产运行时构建（`build_cloud_runtime`）与 P4 live 跑分现在逐能力过出站门（llm/search:web/search:arxiv）——`CLOUD_DATA_UPLOAD_ALLOWED=false` 或未登记指纹即显式 `cloud_upload_not_authorized`，拒绝里附所需指纹；搜索来源（Tavily/arXiv 外送查询）纳入授权面与 UI 指纹表；`LLM_*` 配置面成为 runtime 的配置来源（`DEEPSEEK_API_KEY`/`DEEPSEEK_MODEL` 保留为兼容回退）；新增 `CLOUD_CONFIG_OVERRIDES_PATH`/`CLOUD_SECRETS_PATH` 环境覆盖（可测性/运维）。
