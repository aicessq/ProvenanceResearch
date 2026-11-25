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

## 2026-10-12 云凭证接入、出站授权开启与真实 smoke

| 范围 | 实际命令 | 结果 |
| --- | --- | --- |
| researcher（+4：租户主机精确放行 1、兄弟租户/端口/串 provider 拒绝 3） | multiagent `python -m pytest tests/ -q` | `138 passed` |
| 六目录新契约 | KE venv 六目录 | `128 passed`（零改动） |
| 仓库契约 / Compose 静态校验 | `python3 scripts/check_repo_contracts.py` / `docker compose config -q` | 通过 |
| 出站门八项实测 | 全新进程：runner 同款 `OutboundGate.from_env` 3 项 + 配置面 `check_outbound` 5 项 | 全部 `approved` |
| 真实 smoke（合成 PNG"HELLO 2026"+合成查询，用户已授权） | KE venv 内联脚本，四路各 1 次 | 视觉 qwen3-vl-plus OK 3.3s（结构化 7 条 observations）；LLM deepseek OK 0.5s（11+1 tokens）；Tavily OK 2.0s（2 evidence）；**OCR 失败待用户侧**（见下） |
| P4 live 跑分 | KE venv `python eval/runner.py --mode live`（18 题×3 条件×3 次） | 首跑 162 次运行**全 error**（见下节协议违约）；修复后重跑见 2026-10-12 补丁节 |

- **OCR 失败定位**：token 换取成功（API Key/Secret 有效），`/rest/2.0/ocr/v1/general` 回 `No permission to access data`——百度智能云控制台未给该应用开通"通用文字识别"，属供应商侧产品开通问题；开通后复测，其余三路已通。
- **踩坑记录**：`.env` 中 `CLOUD_DATA_APPROVALS_JSON` 含双引号，必须整体单引号包裹——bash `source` 会把内层双引号按引号语法剥离，得到非法 JSON，`OutboundGate.from_env` 对坏 JSON 静默回落 `{}` 且报 `capability_not_approved`（首轮八项验证即踩中）。
- 出站授权落地方式：指纹经生产路径 `approve_outbound` 五能力登记（`data/cloud_config_overrides.json` 持久化）并镜像写 `.env` 的 `CLOUD_DATA_APPROVALS_JSON`（runner 的 `OutboundGate.from_env` 只读 env，两处一致）；`.gitignore` 增 `**/data/cloud_secrets.json`、`**/data/cloud_config_overrides.json`。

## 2026-10-12 补丁：P4 live 首跑暴露 LLM 消息协议违约 → 修复 → 重跑

| 范围 | 实际命令 | 结果 |
| --- | --- | --- |
| 首跑 P4 live | 同上 | 162 次运行**全 error**（`AttributeError: 'dict' object has no attribute 'role'`，p95 秒级 = 秒挂）；报告自标 `not_a_conclusion`，机械信号 `safety=PASS` 仍有效 |
| 六目录（+1 回归：loop 以 LLMMessage 调 generate） | KE venv 六目录 | `129 passed` |
| researcher / 仓库契约 | 原命令 | `138 passed` / 通过 |
| live 接线冒烟 | `runner.py --mode live --conditions A --runs 1` | 真实指标产出：recall@10=0.7059、mrr=0.6373、citation_acc=0.9583、refusal_acc=0.75、false_refusal=0.4286、p95=5.5s |
| 完整 P4 live 重跑 | `runner.py --mode live`（18 题×3 条件×3 次） | **162 次运行 0 error**（wall 821s）。A/B/C：recall@10 均 0.7059、mrr 0.6373/0.6412/0.6127、citation_acc 0.9535/1.0/0.9776、refusal_acc 0.75/0.75/0.9167、false_refusal 0.4286/0.4762/0.381、answer_mech 0.3095/0.2976/0.381、p95 6.2s/11.0s/8.6s；token A 508k+15k、B 515k+15k、C 536k+24k（cost_unknown=false） |

- **根因与修复**：`agent/loop.py` 三处 `generate` 调用（semantic check/plan/generate）传裸 dict `{"role": "user", ...}`，违约 `LLMProvider` 协议（`Sequence[LLMMessage]`）；fake LLM 从不读 `.role/.content` 所以 129 例 fake 测试全程没拦住，live 适配器（DeepSeek）首跑即全挂。修复为调用方构造 `LLMMessage`（协议严格口径，不在适配器里做 dict 容忍），并把 `eval/runner.FakeEvalLLM` 的 `messages[0]["content"]` 同步收紧为 `.content` 属性访问（fake 对齐真实适配器行为）；新增回归 `test_generate_calls_pass_llmmessage_instances` 断言所有 generate 调用收到的都是 LLMMessage。
- **教训**：fake 的宽容就是漏洞——fake 必须对消息形状与真实适配器同宽严，否则契约测试测不出接缝违约。

## 2026-10-12 LLM 切换：DeepSeek → opencode.ai mimo-v2.6-pro

| 范围 | 实际命令 | 结果 |
| --- | --- | --- |
| 六目录（+1：extra_headers 契约） | KE venv 六目录 | `130 passed` |
| researcher / 仓库契约 | 原命令 | `138 passed` / 通过 |
| 出站门八项（LLM 身份变更后重登记） | 全新进程 runner 门 3 + 配置面 5 | 全部 `approved` |
| 新服务 smoke | `eval.runner._live_llm()` 真实路径 | OK 4.4s（`OK`，15+18 tokens） |
| P4 对比跑（mimo，对比实验非冻结基线） | `runner.py --mode live` | 后台执行中 |

- 接线：runner `_live_llm` 改 `LLM_*` 配置面优先 + 传 base_url（旧代码不传 base_url，纯 .env 切不过去）；`require_live_config` 接受 `LLM_API_KEY`、指纹 preset provider 标签读 `LLM_PROVIDER`；`DeepSeekLLMProvider` 增 `extra_headers` 发 `x-opencode-session`（opencode 网关强制，会话稳定 ID 由 `LLM_SESSION_ID` 或进程 uuid 注入）；test_p4_eval 补 LLM_* hermetic 清理。
- 实测坑：mimo 是推理模型（响应带 `reasoning_content`），smoke 首发 `max_tokens=8` 被推理耗尽致 `content=None` → INVALID_RESPONSE；放开上限即正常。loop/runner 不传 max_tokens 不受影响。

## 2026-10-12 OCR 含位置版复测与收尾

| 范围 | 实际命令 | 结果 |
| --- | --- | --- |
| OCR 含位置版复测 | `BaiduOCRProvider.recognize` 合成图 | OK 0.4s：转录 `'HELLO'`、bbox 归一化 0–1、confidence=None（不伪造）；**四路 smoke 全通** |
| researcher（+3：opencode 网关放行 1、错主机/串 provider 拒绝 2） | 原命令 | `141 passed` |
| 六目录 / 仓库契约 | 原命令 | `130 passed` / 通过 |

收尾改动：`endpoint_guard` 增 `opencode: ("opencode.ai",)`（用户批准）；`.env.example` 补 `OCR_API_SECRET`（用户批准）。


## 2026-10-21 Windows 离线评测自检

- 首次 P4 测试 13 passed / 1 failed，fake runner 被数据集指纹校验阻断。两个冻结 JSONL 的 checkout 是 CRLF，index/冻结数据是 LF；恢复 LF 后字节指纹与冻结件相符。新增 .gitattributes 对这两个路径固定 LF，不修改内容或冻结指纹。
- `python -X utf8 -m pytest tests_bridge/test_p4_eval.py -q`：修复后 **14 passed**。
- `python -X utf8 eval/runner.py --mode fake`：完成 A/B/C 自检，`safety=PASS`；报告 `eval/results/round1.fake.20261021-222536.json`，`mode=fake`、`verified_gold=0`。模拟生成/语义检查及录制搜索仅证明机制可运行，报告中的答案/引用分数不能作为真实模型质量结论。
- 本机常用凭证文件不存在，相关 LLM/Tavily 环境 key 未配置；未发起真实云调用、未安装或加载本地模型。正式 live 质量对照待凭证与有效出站授权就绪。


## 2026-10-21 dev 改进切片 1

- 实施前六目录：130 passed。当前 Windows base Python 3.12.4；研究服务使用根 .venv（system-site-packages），补已声明 loguru/aiosqlite 后 141 passed，9 条既有弃用警告。
- `python -X utf8 -m pytest agent/tests tests_bridge/test_p4_eval.py -q`：52 passed（含 7 个新回归，先红后绿）。
- 控制流语义修正：非法规划拒绝，循环停止原因不被 writer 成功覆盖；无新增真实云调用。


## 2026-10-21 dev 改进切片 2

- `python -X utf8 -m pytest agent/tests tools/tests tests_bridge -q`：84 passed。
- 根 .venv Python 运行 researcher/deep_research_system/tests/test_agentic_service.py：10 passed（结果追加 gaps，原 HTTP/SSE 生命周期保持）。
- 新增缺口闭合/失败/身份接线用例均走真实 AgentLoop/ToolExecutor；HTTP 为录制响应，无密钥无外送。未宣称真实质量改善。


## 2026-10-21 dev 改进切片 3

- 六目录标准命令：151 passed（新增 8 项 repair/预算回归，首批 5 项先红后绿）。
- 根 .venv 运行 researcher/deep_research_system/tests/test_api_v1.py：13 passed；test_agentic_service.py：10 passed。新增 response_model/SSE 局限性不丢失及正文无无据数字断言。
- 前端首次 build 缺 node_modules；按既有 package-lock.json 运行 npm ci --no-audit --no-fund 后 npm run build 通过（43 modules），未修改依赖声明或锁文件。
- 所有新增模型/HTTP 响应均为离线 fixture；未使用云密钥，不把测试通过当 P4 质量收益。


## 2026-10-21 Agent 阅读上下文修正

- `python -X utf8 -m pytest agent/tests -q`：53 passed；包含目标落在原摘要/原 top8 之外的真实 evidence_read 用例。
- 新流程无证据身份变化；消融明确关闭验证反馈内容，避免实验污染。


## 2026-10-21 评测执行接口模块

- `python -X utf8 -m pytest tests_bridge/test_p4_eval.py -q`：14 passed，安全样例额外检查拒答原因。
- 旧 runner fake A/B/C 跑通，报告 round1.fake.20261021-230051.json；仅机械验证，无质量结论。


## 2026-10-21 评测资产字节校验

- check_corpus.py 初次发现 3 项 RFC txt hash 不符，证实为 CRLF；固定 LF 后 28 条 manifest/21 份页级文本校验通过。
- P4 14 passed；题集校验 56 条 schema/配额通过，其中 4 题按既有规则因仓库外语料跳过逐字核对，verified=0 保持不变。


## 2026-10-21 前后对照模块

- `python -X utf8 -m pytest tests_bridge/test_agent_comparison.py -q`：5 passed（旧源码非当前类/hash 拒绝、快照跨 store 复用、三组报告、缺 key 阻断、机制指标）。
- `python -X utf8 -m eval.compare_agents --mode fake`：18×3×3=162 次运行，各组 54 次、0 error，各自安全 5/5 通过；报告 agent-improvement.fake.20261021-230512.json，not_a_conclusion=true、verified_gold=0。
- 此报告为离线脚本模型，不提供真实质量/成本收益结论；live 仍需 LLM/Tavily 凭证和现有出站授权。原 round1 冻结件、题目内容及门槛未改变。


## 2026-10-21 Agent 审查修复

- 两轴审查合并出 3 个实际边界，test_repair.py 新增 3 项先红后绿，11 passed。
- 六目录：160 passed。研究服务上一轮完整回归 142 passed（新增部分作答 API 用例），9 条既有弃用警告；最终收尾会在审查修复后再核对相关接口。


## 2026-10-21 评测失败计账回归

- `python -X utf8 -m pytest tests_bridge/test_eval_accounting.py tests_bridge/test_p4_eval.py tests_bridge/test_agent_comparison.py -q`：21 passed（新两项先红后绿）。
- 检查失败调用计数、已知 token 保留、未知费用标记、失败运行质量及合规为 0；未修改历史结果或冻结阈值。


## 2026-10-21 最终回归与可复现报告

- 六目录标准命令：**162 passed**（最终代码）。研究服务根 .venv：**142 passed**，9 条既有弃用警告。统一前端 npm run build：通过，43 modules。
- check_corpus.py：28 条清单、21 份页级镜像通过；题集 schema/配额校验通过（4 题因既有仓库外来源跳过逐字核对，verified=0）；仓库契约、更新文档本地链接、git diff --check 通过。
- 最终离线对照：agent-improvement.fake.20261021-231729.json，报告代码版本 badeeae32036bc5ed7cd5e0823db6af82ebfb94c，生成时 working_tree_dirty=false；源码指纹与最终代码逐项匹配。三组各 54 次、合计 162 次，0 error，各组安全样例 5/5 通过；not_a_conclusion=true，不是质量结论。
- 实际运行 live 入口就绪检查：启动前明确报缺 LLM_API_KEY/DEEPSEEK_API_KEY 并退出，未发出云请求。真实云质量对照、人工金标准核验、完整 P4 验收仍待外部条件；不进入 Supervisor。
- 修复后 Standards/Spec 两轴均复核通过；审查原始发现与逐项验收见 agent-implementation-review.md。知识引擎代码未变，未重跑依赖本地历史推理环境的 KE 测试；不宣称 KE 全云迁移或真实入库集成通过。


## 2026-10-26 Agnes 配置与运行

- 六目录回归：163 passed。研究服务全量：149 passed、9 条既有警告。
- 最终补充非 DeepSeek 缺模型/端点不得使用 DeepSeek 默认地址后，providers/tests + test_agentic_service.py + test_endpoint_guard.py：75 passed、3 条既有警告。覆盖精确主机、协议、端口、跨供应商绑定、Agnes 身份、旧网关头隔离及缺配置失败。
- 前端 npm run build 成功，43 modules。五项真实云合成服务检查均成功，OCR/Vision 均转录 HELLO 2026。前端、后端文档、代理后的配置/任务列表均 200，三项基础设施 healthy。
- 两个真实任务完成生命周期但拒答：citation_gate_failed（摘要被模型声明为全文），invalid_planner_output/no_progress。保留失败记录，不把连接成功称为质量通过；未运行正式 P4 对照，完整 KE 集成仍未验收。重启方法和边界见 windows-local-run.md。

- Windows 契约检查首次未启用 UTF-8，读取中文 git 输出触发 GBK 解码异常；按本机既有命令加 `-X utf8` 后仓库契约通过，不修改业务代码规避环境问题。


## 2026-10-26 本地 Embedding 例外接入

- 新增 reranker 关闭不得加载权重的回归先红（1 failed / 11 passed），接入 RERANKER_ENABLED 后通过；本地模型加载增加 local_files_only=True、trust_remote_code=False 的契约测试。Embedding、retriever、默认配置针对性回归：14 passed。
- 配置视图新增本地 Embedding 无需云 key、其他能力不因此放宽的测试，先红后绿：12 passed。补缺路径仍显示未配置的检查。
- KE 全量测试两次在收集期因 safety_guard.py 读取报 Bad file descriptor、随后文件消失而中断（4 errors / 28 deselected）。该文件初始无 diff，按 HEAD 恢复后再次在读取时消失；未修改或删除安全逻辑，已请求用户核查本机隔离记录。该环境阻断未解决时，不宣称全量通过或文档入库/检索验收通过。
- 本机原为空的 PostgreSQL 库通过现有迁移升级至 0002_ingest_task_reliability；未修改 migration/schema 源码，未对测试库以外数据执行清表。

- 用户处理本机安全软件后，按 HEAD 恢复原 safety_guard.py（没有源码 diff），KE 完整单元回归：100 passed、34 deselected。配置回归最终 12 passed（含缺路径）；仓库契约通过。之前的文件读取环境阻断已解除。
- 官方 BGE 权重下载过程中连接中断，使用同一官方源与固定 revision 续传完成，权重 437955512 bytes；生产加载完全离线。真实本地模型生成三个 768 维有限值向量，相关/不相关余弦分别约 0.902 / 0.301；该合成检查不构成质量评测。
- 知识库 /health 200，/api/v1/health/ready 为 ok，PostgreSQL/Redis/Qdrant/Worker 全部正常。研究服务重启后，经统一前端代理的配置显示本地 embedding 已配置。

- 真实入库任务 completed，产生 parent/child 各一个；英文查询因既有 note 类型推断首次空召回，显式 standard 后命中。随后实际工具调用暴露索引身份丢失；新增回归先红后绿，补齐身份传递和不一致拒绝。
- 最终核心六目录：164 passed；KE 完整单元回归：101 passed、34 deselected。真实 HTTP + KBSearchTool 验证 PASS：一个 vector chunk、一个 K 前缀引用。记录在忽略的 .env.run/local-kb-smoke.json。没有执行正式 P4 对照，不宣称大规模或中文召回质量。

- 收尾新增缺失/混合身份不得注册部分证据的回归，工具层 25 passed；最终六目录 165 passed。拆分后的 API 身份 schema 回归独立执行 1 passed；仓库契约及 diff 检查通过。


## 2026-10-26 正式本地 KB 测评准备

- 新 local-kb-v1：60 题、16 份固定原件；原始文件哈希校验及题目标注源文校验通过。真实生产上传/Worker 在独立评测资源生成 1892 个 child chunks，62 个源文片段全部映射；Qdrant 精确成员及模型身份与数据库一致。
- 测评模块10项测试通过（审查发现的实际反例先红后绿）；最终核心六目录175 passed。仓库契约、diff 检查通过。两轴审查问题均修复并静态复核，见 local-kb-evaluation-review.md。
- 题集与代码将在正式计分前固定提交。候选标注 human_verified=0，保留所有故障、缺失运行及 token 未知标记，不将自动化测量作为旧 P4 人工验收或多模态验收通过。


## 2026-10-26 低频补测配置

- 新增分层抽样、全局请求间隔、子集分母3项回归先红（3 failed / 10 passed），实现后13 passed。原60题配置与120秒deadline保持不变，补测24题/48任务/20正4负分母独立。

- 审查补充：等待取消不得虚增云调用次数；PacedLLM 继承 UsageLLM 保持 run_condition 记账契约。真实 runner 的正常返回/模型异常及等待取消均覆盖，测评模块15项通过。首次全量命令误写不存在的 eval/tests，未收集测试；改用文档中的六目录标准命令。
- 最终六目录回归：180 passed；静态两轴审查问题全部修复。


## 2026-10-26 正式测评实测结果

- 两轮均complete=true：各60题×3轮检索，共360次真实HTTP/1080条分通道记录；Agent首轮120次、低频补测48次。两轮前后chunk/Qdrant哈希一致，16文档/1892chunk/62事实映射不变。
- BGE严格证据Recall@10=65.625%、MRR@10=0.5481；两轮排名指标一致。旧/现Agent低频补测作答5/20与1/20，当前19次规划格式失败；不作为算法提升或旧P4人工验收通过。详见local-kb-evaluation-report.md。
- 汇总快照断言任务数/完整性/审计一致性，人工审核表168行留空评分；图表已渲染检查。最终代码回归180 passed（报告仅新增文档与实测产物，无业务源码修改）。

- 交付复核：原始文件哈希、快照一致性、168任务唯一性与token合计核验通过；两轮全部540键排名一致。测评模块最终15 passed，报告补齐多源all-facts@5指标；人工审核字段仍为空。

## 2026-11-24 三段式研究图首轮回归

- `knowledge_engine/.venv/bin/python -m pytest agent/tests -q`：38 通过；`tools/tests -q`：25 通过；agent、tools、providers、evidence、ingest 与 tests_bridge 六目录合计 140 通过。
- 在 `researcher/deep_research_system` 运行 multiagent 环境的 `python -m pytest tests/ -q --disable-warnings --tb=short`：149 通过。覆盖同题按证据选择提交或抓取、并发额度、失败去重及提醒、两轮澄清恢复、超时假设和等待取消。修复两项仍接旧拓扑替身的服务用例后恢复全绿。
- 以上均为离线结果，本轮未运行云端对照。

## 2026-11-24 增量核验回归

- multiagent 环境运行 researcher 全套，152 通过。验证检索额度为零仍可完成两轮删改、相同断言复用核验、缺证回流原上下文、失败断言不发布。

## 2026-11-24 统一前端构建

- `npm --prefix frontend run build` 通过 TypeScript 检查与 Vite 构建。本次记录是构建结果，浏览器会话验收另计。

## 2026-11-24 定向补证回归

- researcher 全套 153 通过。补证用例验证只调用一次模型规划、拒绝递归补证，并在只剩一个检索额度时仅发出一条查询。

## 2026-11-24 对照框架离线验证

- multiagent 环境运行 `python eval/runner.py --mode fake --freeze eval/baseline/three-stage.freeze.json --runs 1`，三条件 54 次运行，安全样例全过。脚本模型仅用于评测链路验证；其中共享图首证据排序回归待真实对照前修正。六目录契约 140 通过，researcher 153 通过。

## 2026-11-24 Writer 排序复测

- 同一离线冻结集 54 次重跑安全样例全过，共享图的机械引用命中率由 0.0714 恢复到 0.5714，与两条离线对照一致；researcher 153 通过。脚本模型结果不作为真实质量结论。

## 2026-11-24 双入口与浏览器联测

- researcher 全套 154 通过。旧报告 HTTP 使用真实 LangGraph 和测试模型，核对认证、报告与引用格式、晚订阅终态；服务层验证重复取消只落终态一次。浏览器用本地临时测试账号，验收登录后发题、收到澄清提示、提交补充以及显示一条已验证引用和完成事件。
- 真实对照使用现有出站授权启动，OpenCode 返回 HTTP 403，订阅因付款授权中断。连续错误后已停止进程，未产出有效对照指标。DeepSeek 候选配置当前没有匹配的出站授权。

## 2026-11-24 无结论及守卫验收

- researcher 157 通过、六目录契约 140 通过、统一前端构建及仓库契约通过。新增用例覆盖超范围提前结束、慢工具超时后留痕、供应商回报突破探索预算后的产出拦截。

## 2026-11-24 全文定位验收

- researcher 158 通过，六目录契约 142 通过。使用合成 PDF 验证 arXiv 两个版本共存、全文第 2 页可定位、损坏 PDF 只保留摘要；真实研究图验证长正文后段从定向读取进入生成和语义核验。

## 2026-11-24 对照重跑与云端预检

- 六目录契约 143 通过，离线 54 次对照再次通过机械安全检查。使用现有配置实测云模型预检返回 AUTH_FAILED 并退出，未启动逐题评测。

## 2026-11-24 修订引用回归

- researcher 全套 159 通过。新增场景验证修订时伪造引用仍被记为失败，只发布已核验的断言。

## 2026-11-24 计划变更与离线复测

- researcher 全套 160 通过，覆盖重复改写后的证据重新登记、三次实际变更上限和变更历史。冻结题集三条件 54 次离线运行，安全检查通过；仓库契约通过。重新检查云模型仍为 AUTH_FAILED。

## 2026-11-24 同地址全文回归

- researcher 全套 160 通过，六目录契约 145 通过，仓库契约通过。同地址并发覆盖成功与失败两条路径，验证仅一次下载及两套引用身份并存。
- 应用设置与评测环境确认使用同一已授权的 OpenCode 配置，模型实测预检仍返回 AUTH_FAILED。

## 2026-11-24 推理模型核验回归

- researcher 161 通过，六目录契约 146 通过。真实 OpenCode 合成断言核验通过，记账 123 输入和 37 输出 token。修复前的对照继续保留，作为分析运行错误的依据。

## 2026-11-24 研究判断题组预检

- 六目录契约 147 通过，仓库契约通过。独立冻结题组 6 次离线运行成功，安全检查通过。OpenCode Go 使用 hy4-flash-free 的合成预检返回 OK。

## 2026-11-24 云端旧模型诊断及评测时限

- 旧模型 MiMo 真实报告共 162 次，固定混合 12 次和旧 Agentic RAG 5 次为 30 秒请求超时，共享图 49 次为供应商返回的正文类型错误；修复前结果不作为新版质量结论。
- 六目录契约 149 通过，验证配置超时传入模型适配器、非有限值被拒和旧基线到任务时限会取消。仓库契约通过。

## 2026-11-24 深度题初轮与推理额度回归

- Hy4 初轮真实结果 6 次，固定混合 3 次请求超时，三段式 3 次明确拒答，均无可发布正文。报告保留在 eval/results/research-judgment-hy4。researcher 162 通过，新增回归验证先消耗推理 token 的模型仍可完成定界、检索和引用核验，全程计账。

## 2026-11-24 三题 Hy4 真实复跑结果

- 同模型两条件 6 次，90 秒模型请求、240 秒单题截止。固定混合两份部分回答及一次单题超时；三段式三个无结论、候选数 25/10/24、逐断言核验数均为零。已报告 token 逐题为固定混合 22,009/17,265/未知，三段式 10,023/11,380/8,419。安全样例通过。原始报告及逐题输出保存在 eval/results/research-judgment-hy4-880644c。

## 2026-11-24 Writer 格式回归

- researcher 164 通过，六目录契约 149 通过，前端构建通过。新增用例覆盖检索额度耗尽后仍能修复截断的草稿，以及格式一直失败时两轮后拒答，无断言发布。

## 2026-11-24 Hy4 Writer 截断定位

- 7d17000 复测三题均无正文，rj01 两次截断后提交两条失败断言，rj02/rj03 各三次截断。报告位于 eval/results/research-judgment-hy4-7d17000。延长策略本地 researcher 164、六目录契约 149 通过。

## 2026-11-24 Hy4 截断修订复测

- 1c005ae 云端复跑三题各有两条断言进入核验，全部未通过；报告位于 eval/results/research-judgment-hy4-1c005ae。researcher 165、六目录契约 149 通过，回归覆盖先截断、语义判失败、随后仍保留较大写出额度并通过核验。

## 2026-11-24 定界恢复回归

- researcher 166 通过。新增用例验证从长模型响应截断恢复为两个可用的子问题，并核对定界重试用量。暂停中的批量对照未恢复。

## 2026-11-24 多来源 Writer 回归

- researcher 167 通过。新增真图场景在单来源八页排在前面的条件下，验证 Writer 仍能看到另一个来源的两个版本及第三个来源。

## 2026-11-24 研究判断样例的引用诊断

- f5caa9e 三题均成功定界，前两题候选断言被原文引语检查拒绝，出境题草稿仍有截断和语义拒绝。后端 167、六目录契约 149 通过；测试验证截断核验产生诊断且不发布断言。

## 2026-11-24 Hy4 语义截断诊断

- afc36c0 三题中两题共四次 verify 均 length，第一题无候选证据。后端 168、六目录契约 149 通过，新增回归覆盖核验截断后完整 yes 才发布，且两次均计入预算。

## 2026-11-24 Hy4 推理设置探针

- 2fa7b10 真实三题仍全部未发布，诊断覆盖 arXiv 不可用后的 Web 回退、Writer 截断、核验否定及计划全截断。适配器新测试验证仅显式配置才发送 reasoning_effort；后端 168、六目录契约 152 通过。

## 2026-11-24 Hy4 三题逐题验收

- 296fb03 使用显式 reasoning_effort=none，三题首次均发布正文；逐题验收仍为 0/3。第一题缺 Self-RAG 且误标完整，第二题缺版本结果对照，第三题将旧规阈值用于当前建议。原冻结批量评测停在 45 次。详见 eval/results/research-judgment-hy4-smoke-296fb03/逐题验收.md 及同目录 JSON。

## 2026-11-24 整体覆盖回归

- 后端 169、六目录契约 152 通过。新增真实图回归覆盖各子问题都有已核验的断言但缺少点名材料时仍发布部分回答。

## 2026-11-24 官方版本回流回归

- 后端 170、六目录契约 152 通过。真实图用模拟官方材料覆盖先核验旧规则、发现新规定后重新核验并停止发布冲突的旧结论。

## 2026-11-24 全文地址解析回归

- f13146b 真实样例三题均发布部分正文，版本题两次把网址传作 ID 而失败。修复后后端 170、六目录契约 153 通过，验证已登记地址命中、未登记地址不出站。

## 2026-11-24 搜索预览预算回归

- 研究后端 171 通过；agent、tools、providers、evidence、ingest、tests_bridge 共 153 通过。回归用四条并行检索各返回八条长中文结果，确认既能进入下一个探索回合，也能访问未展示预览的完整片段。

## 2026-11-24 Hy4 三题复测与批量评测门槛

- b0f8e34 与 ca228f7 用同一冻结题、额度和 hy4-flash-free（reasoning_effort=none），各实际运行 D 条件三题一次。ca228f7 三题均有部分回答；b0f8e34 一题断言生成失败、两题有部分回答。两轮逐题验收均为 0/3，仍暂停批量评测。报告和实际正文见 eval/results 对应提交目录。
- b0f8e34 的版本题使用了本地库，但缺两版结果和局限对照。法规题引用了当年累计门槛，缺决策树及适用例外。另用同一 arXiv 查询端点复查得 HTTP 429。

## 2026-11-24 截断草稿回归

- 研究后端 172 通过；agent、tools、providers、evidence、ingest、tests_bridge 共 153 通过。新增回归覆盖首次截断、两次重试仍无法解析、完整断言经核验保留、错误引用及未闭合断言未发布。

## 2026-11-24 论文接口不可用回归

- 研究后端 173 通过；agent、tools、providers、evidence、ingest、tests_bridge 共 153 通过。模拟真实 arXiv 工具收到 HTTP 429，确认提示进入原探索对话、随后调用私库取得全文、最终只发布经校验的断言，总计两次工具调用。

## 2026-11-24 截断草稿与论文取证提示实测

- 5a12f0a、a56cb54 分别用相同冻结题、额度与 hy4-flash-free（reasoning_effort=none）各跑三个 D 样例，均为三份部分回答，人工验收各 0/3。5a12f0a 法规题的首次草稿截断后仍发布了四条通过核验的断言，两次后续回合未生成新草稿。
- a56cb54 实验题在 arXiv 查询失败后改用私库，仍只给 Writer 提供了 Self-RAG 的参考文献页。版本题未取得两版正文；法规题漏查已生效的认证办法。两轮实际正文和引用见 eval/results 对应提交目录。批量评测仍暂停。前端生产构建、冻结语料完整性和仓库契约检查通过。

## 2026-11-24 探索预览压缩回归

- 研究后端 174 通过；agent、tools、providers、evidence、ingest、tests_bridge 共 153 通过。四条查询各返回八条长中文结果；预算充足时保留预览，空间紧张时使用来源标识继续调用证据读取，两种情况均可读回原片段。

## 2026-11-24 证据读取守卫回归

- 研究后端 175 通过；agent、tools、providers、evidence、ingest、tests_bridge 共 153 通过。新增回归验证同一来源三个不同窗口均执行，三次缓存重复读取仍触发无进展停止。

## 2026-11-24 抓取拦截原因回归

- 研究后端 176 通过，六目录契约 153 通过，统一前端生产构建通过。新增已登记来源 MIME 拦截轨迹，验证工具把原因交给 Agent 且最终无结论报告可显示原因。通过实际抓取工具复查政府官网与 arXiv，均返回“来源必须解析到公网地址”。

## 2026-11-24 探索预算与取证真实样例

- b3f93e6、9e176ff 用同一冻结题、额度与 hy4-flash-free 各跑三个 D 样例。前者两题部分回答、一题无结论，后者三题部分回答。人工验收均为 0/3，批量评测仍暂停。
- 两轮版本题均从私库取得 v1/v2 版本材料。9e176ff 核对两版的摘要定义并写出主结果，尚缺两版实验结果与局限的逐项对照。实验题缺完整同预算方案；法规题缺决策树。实际正文、来源与用量见 eval/results 各对应提交目录。

## 2026-11-24 点名论文与版本检索回归

- 六目录契约 157 通过，语料页级镜像与仓库契约通过。新增四个回归，覆盖同一真实语料上的 Lost in the Middle、Self-RAG 和两个指定版本。复查先前误命中的查询，指定论文进入首位。

## 2026-11-24 多查询写作候选回归

- 研究后端 177 通过，六目录契约 157 通过。新增双版本并行查询各返回八页的用例，确认写作收到两版各自前四页，而两次检索仍记在同一任务预算内。

## 2026-11-24 点名检索与写作融合的真实样例

- db765c3、67b392b 用同一冻结题、额度、hy4-flash-free 和 local-bigram-v3，各跑三个 D 样例。前者两题部分回答、一题无结论，后者三题部分回答。人工验收均为 0/3，批量评测继续暂停。
- 67b392b 实验题纳入 Lost in the Middle 实验页并提出两组做法，仍缺完整同预算实验方案；版本题引用 v1/v2 两版的结果材料但缺逐项对照；法规题抓取两份官方网信办正文均报公网地址校验失败，未形成完整决策树。实际正文和用量见 eval/results 各提交目录。

## 2026-11-24 现行法规引用批量核验回归

- 研究后端 178 通过，六目录契约 157 通过。官方新材料到达后，回归验证原来接受的旧口径被撤回；批量结果乱序按 ID 关联，缺少一项时走单条复核，两个路径都只发布通过的断言。

## 2026-11-24 单 Agent 状态与剩余额度回归

- 研究后端 179 通过，六目录契约 157 通过。回归验证检索后不重复发送未变计划，修改计划后发送新问题，工具与轮次额度按执行耗减。

## 2026-11-25 损坏草稿恢复回归

- 研究后端 181 通过，六目录契约 157 通过。覆盖明确截断、提供正常终止状态但结构损坏、外层有效但个别条目非法三种情况。均验证无效结构、伪造引用和语义不支持的断言不得发布，完整且获核验的断言可保留。

## 2026-11-25 共享核验、探索额度与草稿修复真实样例

- 25960dc、98933a8、a519526 用同一冻结题、额度和 hy4-flash-free 分别各跑三个 D 样例，均发布三份部分回答，人工验收均 0/3。25960dc 法规题相较上一单样例的核验输入从 12,123 token 降为 6,008 token；生成的断言数量不同，此处只记录实测用量。
- a519526 实验题缺同预算方案，版本题有两版定义和示例但缺实验和局限对照；法规题缺决策树且同时列出当年及上年为待查口径，人工对照现行规定后判未通过。批量评测仍暂停。实际正文见 eval/results 对应提交目录。

## 2026-11-25 现行条文与旧口径备选回归

- 研究后端 182 通过，六目录契约 157 通过。新增八份较新政策解读挤占列表的场景，确认当前正式条文进入写作和核验；模型夹具按提示拒绝将已替换口径作为当前备选，同时保留有引用支撑的历史断言。

## 2026-11-25 抓取受阻时替代取证提示回归

- 研究后端 183 通过，六目录契约 157 通过。使用真实抓取工具的模拟响应覆盖受限 MIME，检查有无私库时反馈只列启用能力，拒答仍保留原错误原因。

## 2026-11-25 现行条文优先与抓取受阻样例

- c933045、bbbf47a 用同一冻结题、额度和 hy4-flash-free 各跑三个 D 样例，两轮均发布三份部分回答，人工验收 0/3。两轮法规题均使用当年累计口径，仍缺可执行的逐分支决策树。
- bbbf47a 版本题在 arXiv 正文抓取受阻后改用网页检索，仍没有两版结果与局限对照；实验题给出两组框架和改变建议的定性条件，缺完整同预算实验。批量评测仍暂停。两轮逐题验收和原始输出见 eval/results 对应提交目录。

## 2026-11-25 arXiv 版本定位回归

- 研究后端 183 通过，六目录契约 157 通过。参数测试覆盖一个版本、两个版本、版本附在编号或独立出现、多个不同编号，同时保留题名短语与普通查询的行为。

## 2026-11-25 写作上下文预算回归

- 研究后端 184 通过，六目录契约 157 通过。八条长证据、首轮写作截断且剩余额度偏低的场景中，后续写作用压缩后的高位证据完成断言生成；任务保留八条原始证据，发布只引用实际发送且获核验的断言来源。

## 2026-11-25 指定论文定位与收尾预算实测

- c901a9a、a480b97 用同一冻结题、额度和 hy4-flash-free 各跑三个 D 样例，两轮均发布三份部分回答，人工验收均 0/3。c901a9a 实验题改用引号题名检索，候选由上一轮 15 项变为三篇点名论文，但只有摘要。
- a480b97 实验题随后调取了私库证据。法规题在首次截断后实际完成两次生成请求，但把上年累计口径当作当前标准合同条件，且缺决策树；版本题缺两版量化结果与局限的完整核对。三题正文及验收见 eval/results 各提交目录；批量评测仍暂停。

## 2026-11-25 官方条文窗口回归

- 研究后端 184 通过，六目录契约 157 通过。将新规则计量与衔接条文放在第 1,000 字之后，通过真实 WebSearchTool 的模拟响应和 LangGraph 验证写作、批量核验都获得原文窗口，范围仍为 snippet。

## 2026-11-25 保留官方条文窗口的真实样例

- 99699fe 用同一冻结题、额度和 hy4-flash-free 跑三个 D 样例，三题均为部分回答，人工验收 0/3，批量评测仍暂停。法规题没有复现上年累计错误，引用了当年累计条文；两处全文抓取仍被公网地址校验阻止，决策树与待核验事实未完成。实验题缺同预算可执行方案，版本题缺两版结果和局限对照。实际正文见 eval/results 对应提交目录。

## 2026-11-25 部分交付的具体缺口回归

- 研究后端 186 通过，六目录契约 157 通过。回归验证只有部分子问题有核验断言时，覆盖检查可发回分支所需的具体条文，同一探索上下文补查后完成发布；普通事实和整体缺口流程保持相同结果。

## 2026-11-25 多断言共享证据核验回归

- 研究后端 187 通过，六目录契约 157 通过。新增三条断言共享同一证据窗口的 case，批量判定乱序返回，两个通过的断言发布、一个不通过的断言被移除。

## 2026-11-25 交付物覆盖与共享证据核验样例

- 1d01af3、19bd9d4 用同一冻结题、额度和 hy4-flash-free 各跑三个 D 样例，两轮均发布三份部分回答，人工验收 0/3。19bd9d4 版本题和法规题各发出一次覆盖检查，实际返回了具体缺口；实验题无覆盖调用。
- 三题仍缺同预算可执行实验、两版结果和局限对照或完整决策树，批量评测继续暂停。两轮原始输出和逐题验收见 eval/results 对应提交目录。

## 2026-11-25 回流预留对账回归

- 研究后端 191 通过，六目录契约 157 通过。首轮写作已消耗 12,000 token（任务总额 20,000）后仍能在原对话内补证；低消耗路径仍保护未花的预留。覆盖正常子问题缺口和具体交付缺口。

## 2026-11-25 回流时间对账回归

- 研究后端 191 通过，六目录契约 157 通过。可控时钟复现总时限 180 秒、首次收尾已耗时 145 秒的场景，反馈回到原探索上下文时有 35 秒可用；未消耗收尾时间时仍保留 45 秒。

## 2026-11-25 已耗收尾额度对账的真实样例

- ed9bd90、7c350d6 各用原冻结题组及 hy4-flash-free 运行一次 D，均发布三个部分回答，人工验收均 0/3。合并 token 与时间对账的样例三题均止于 budget_exhausted，未记录到首次写作后的探索模型请求。回流已由夹具复现，真实样例仍未验通，批量评测暂停。

## 2026-11-25 探索证据索引压缩回归

- 研究后端 192 通过，六目录契约 157 通过。四轮搜索返回 32 条长证据的测试覆盖全文预览、元数据和仅编号三种预算情形，最紧情形仍能在同一对话内按编号读回完整片段。

## 2026-11-25 预算拒绝报告回归

- 研究后端 192 通过，含实际回报超预留的检查。在含 LangGraph 的研究环境中，25 项评测桥接测试通过，含预算预检拒绝且零模型请求的回归。知识引擎环境的六目录契约 157 通过、1 跳过（该环境不含 LangGraph）；研究环境不含 PyMuPDF，三个 PDF 工具测试在知识引擎环境通过。

## 2026-11-25 规划压缩与模型预算诊断实测

- 115efd7、41d1071 各运行冻结题组一次 D。两轮均两题部分回答、法规题无已核验正文，人工验收 0/3，批量评测暂停。41d1071 三题首次受阻均为规划输入预检；输入预估分别为 12,058 / 16,733 / 22,069 token，可用额度分别为 9,711 / 9,320 / 9,112。法规题的语义核验未发出，请求在预检被拦。逐题正文和诊断见 eval/results 对应提交目录。

## 2026-11-25 主动压缩规划历史的回归

- 研究后端 193 通过，六目录契约 157 通过、1 跳过（知识引擎环境不含 LangGraph）。新增放宽至一百万 token 后仍主动压缩的场景，确认原始文段可按编号读回，下一轮可见刚读取的完整结果。

## 2026-11-25 放宽预算下的规划历史压缩复测

- 7243705 用 hy4-flash-free 在放宽预算下运行冻结三题，均未触发预算拦截。rj01/rj02/rj03 总用量为 88,247 / 82,957 / 104,547，合计 275,751；此前各取一次未触发预算拦截的样例合计 1,806,236。法规题规划输入从 1,333,043 降至 17,642，规划请求数分别为 31 和 5，不能把两次路径差异全归因于压缩。三题仍是部分回答，批量评测未启动。原始报告位于 eval/results 对应提交目录。

### 2026-11-25 | 核验指明缺口后补查回归

- 研究系统测试 198 通过。新增覆盖补证成功、重复已查查询、立即重提、轮次耗尽以及覆盖结果无效五条轨迹。
- Agent、工具、服务商、证据、入库及桥接测试 157 通过、1 跳过。仓库契约通过。

### 2026-11-25 | 放宽额度后的缺口回流实际样例

- c562ca4 在冻结三题上用 hy4-flash-free 各跑一次 D，设每题 64 轮、128 次工具、1000 万 token、900 秒。逐题输入/输出 token 为 rj01 305,487/10,825，rj02 166,125/11,550，rj03 478,434/17,569；合计 989,990。三题均没有 token 预检或回报拦截，rj03 达到工具上限，另两题以无进展收尾。
- 三题在首次覆盖核验后分别出现 15、10、3 次探索模型请求。人工预检 0/3，三题均为部分回答，正式对照评测暂停。rj01 缺完整预算公式和改判阈值，rj02 缺双版本结果与局限对照，rj03 缺完整决策树且关基条文引用旧版译文。
- 原始报告和逐题验收见 `eval/results/research-judgment-hy4-token-diagnostic-c562ca4-20261125-114932/`。本轮为单次预检，未运行对照组。

### 2026-11-25 | 补证材料进入写作的回归

- 研究后端 199 通过。新增 LangGraph 回归，八条初版显式阅读占满首轮写作窗口后，覆盖核验发回缺口，补查的两条第二版原文进入下一轮写作并经核验发布。
- 六目录契约 157 通过、1 跳过。仓库契约通过。

### 2026-11-25 | 论文双版本正文实跑预检

- c498254 用相同放宽额度和 hy4-flash-free 单跑 rj02。四次写作都收到 v2 第 1、3 页，上一轮四次只收到第 1 页。本轮第 3 页自首次写作已在窗口中，覆盖核验后补查三次探索模型请求，后续写作所见 v2 页面未增加。
- 正文引用 v2 图 2 并给出部分验收步骤，仍缺两版实验结果、局限对照和上线通过条件，人工预检未通过。实测 132,427 输入与 7,826 输出 token，合计 140,253，33 次工具调用，未触及 token 限额。本轮只有一个样本，未运行对照组。
- 原始报告及正文位于 `eval/results/research-judgment-rj02-hy4-c498254-20261125-120557/`。

### 2026-11-25 | 以证据 ID 抓取已登记来源的回归

- 研究后端 199 通过，包括从搜索证据 ID 到正文核验的 LangGraph 场景。六目录契约 157 通过、1 跳过，包括分别以 v1、v2 摘要证据 ID 抓到对应 PDF 页，重用下载缓存，并拒绝未登记的 v3 URL。仓库契约通过。

### 2026-11-25 | 正文证据 ID 抓取与论文版本实跑

- 6e536e5 现场检索 arXiv 获得 v1 和 v2。两条摘要证据 ID 都解析到已登记来源的版本 PDF，下载均被当前环境的公网地址校验拦下。模型预检也记录了证据 ID 已解析、下载被校验拦截的实际轨迹。
- hy4-flash-free 单跑 rj02，254,937 输入和 11,218 输出 token，合计 266,155，103 次工具调用，以无进展结束。私库 v2 第 9 页进入四次写作，首轮片段 700 字，后续只剩页尾 112 字。正文仍缺双版本实验及局限对照与可执行验收，人工预检未通过。
- 原始报告及正文位于 `eval/results/research-judgment-rj02-hy4-6e536e5-20261125-121040/`。

### 2026-11-25 | 同一来源的多段摘录

- 研究后端 200 通过。真实 LangGraph 模拟抓取覆盖一次读页尾时保留原文开头，以及先读结果段、再读页尾时两段都进入写作、各自按原文定位并通过语义核验。六目录契约 157 通过、1 跳过，仓库契约通过。

### 2026-11-25 | 同页双摘录三题实跑预检

- eb92302 使用 hy4-flash-free 和放宽的相同单题额度，三题各独立实跑一次 D。rj01 输入/输出为 269,121/7,400，rj02 为 126,623/8,840，rj03 为 406,611/13,673，合计 832,268 token。三题均未触及 token 限额；rj03 达 128 次工具上限，其余以无进展结束。
- rj02 正文新增 v2 的分查询类型引用精确率，第四次写作实际收到 v2 第 7 页的两段原文（各 350 字）。rj01 没有看到双摘录，rj03 共有六条写作输入记录使用双摘录。
- 人工预检仍为 0/3。rj01 缺同预算实验方案和改判阈值；rj02 缺完整双版本结果和局限对照、完整上线验收方案；rj03 缺完整决策树，且发布的一条断言把上年累计也列为当前审核口径。实跑正文与原始报告位于 `eval/results/research-judgment-rj*-hy4-eb92302-20261125-121650/`。正式对照评测未启动。

### 2026-11-25 | 复合适用条件回归

- 研究后端 200 通过，其中混合两个累计时点的决策树断言即使有引用支撑，也会因列出的旧口径未获当前适用核验而被拒；保留通过的现行口径和历史说明。批量结果无效时回到单条适用性核验。六目录契约 157 通过、1 跳过，仓库契约通过。

### 2026-11-25 | 适用条件核验重放与法规题实跑

- 2511990 用 hy4-flash-free 定向复核先前被错误发布的同一断言，使用已保存的官方答记者问和旧标准合同办法摘录，以及现行规定的冲突摘要。批量和单条均拒绝混用当年与上年累计。批量同时通过现行口径与明确标为历史的说明。定向复核独立用量 4,267 token。
- 同提交单跑 rj03 消耗 815,179 输入和 32,712 输出 token，合计 847,891，达到 128 次工具上限；未触及 token 限额。有一次批量核验输出截断并回退。正文未再发布上年累计口径，但仍错误引用《网络安全法》修正前的第三十七条，且决策树与逐分支依据未交齐，人工预检未通过。
- 实跑正文和定向复核位于 `eval/results/research-judgment-rj03-hy4-2511990-20261125-122346/`。正式对照评测未启动。

### 2026-11-25 | 现行文本搜索和同名转载排序

- 研究后端 200 通过；扩展实图回归加入八份较新解读、四份较新同名旧文转载，验证明示修订依据的正文及另一部法规优先进入写作和核验。六目录契约 157 通过、1 跳过，仓库契约通过。

### 2026-11-25 | 网页时间过滤回归

- 研究后端 201 通过，包含同一查询先不限时、再按年查，供应商收到两次不同请求，year 与 y 只发一次。六目录契约 157 通过、1 跳过，仓库契约通过。

### 2026-11-25 | 现行法规检索探针及完整实跑

- 1c4ac81 用 hy4-flash-free 单跑 rj03，699,350 输入、33,123 输出，合计 732,473 token，90 次工具调用，以无进展结束。七次网络安全法检索仍有六次带旧条号。正文未发布旧条号，仍缺修正后关基条文与完整决策树，人工预检未通过。
- cd6b9c6 单独使用现有搜索工具对同一查询分别执行不限时和按年请求。按年结果首条是深圳市公安局发布的修订文本，提供关基出境第三十九条。该调用不涉及模型，完整实跑仍为前一提交。
- 实际正文和两种检索探针位于 `eval/results/research-judgment-rj03-hy4-1c4ac81-20261125-123513/`。正式对照评测未启动。

### 2026-11-25 | 已核验断言编排回归

- 研究后端 202 通过。覆盖有效条件分支的层级输出，以及模型试图引用未放行编号时回退为已核验正文。六目录契约 157 通过、1 跳过，仓库契约通过。

### 2026-11-25 | 编排重复与漏项回归

- 研究后端 203 通过。真实图回归覆盖同一核验断言同时出现在依据区和树中、漏掉另一条时，保留树并把漏项补到依据区；未知编号仍安全回退。六目录契约 157 通过、1 跳过。

### 2026-11-25 | 三题正文编排实跑与重复编号重放

- c046edd 用 hy4-flash-free 分别运行同预算实验、论文版本、法规三题。输入/输出分别为 53,456/7,448、109,830/12,172、505,354/21,327 token，合计 709,587。三题都调用了编排，随后走平铺回退，人工预检 0/3。法规题达到 128 次工具上限，并再次错误发布上年累计条件；三题未触及 token 上限。
- 另对前两题的已核验断言各请求一次编排，观察到跨章节重复编号。b079b5c 离线使用同一模型输出重放，成功生成结构化正文，并恰好保留原样本的 21 条和 19 条已核验断言。重放未增加事实，不能替代整题验收。
- 实际正文和重放位于 `eval/results/research-judgment-rj*-hy4-c046edd-20261125-124731/`。正式对照评测未启动。

### 2026-11-25 | 跨断言冲突撤回回归

- 研究后端 204 通过。新增实图回归令引用核验先通过三个断言，覆盖核验撤回旧口径伪装成当前审核输入的一项。后续重提仍被拒，历史说明和现行口径进入排版与发布，原缺口继续报告。六目录契约 157 通过、1 跳过，仓库契约通过。

### 2026-11-25 | 冲突引用定位回归

- 研究后端 204 通过。冲突场景增加伪造的相反片段，保留该片段试图撤回的历史断言，只撤回能定位到相反内容的当前口径；撤回事件保存原文及其编号。六目录契约 157 通过、1 跳过。

### 2026-11-25 | 覆盖核验格式恢复

- 研究后端 204 通过：回归用错编号但可唯一定位反证的模型输出、捏造片段和未知缺口分组同时验收。六目录契约 157 通过、1 跳过，仓库契约通过。

### 2026-11-25 | 三题冲突核验实跑及定向重放

- 240c75e 用 hy4-flash-free 各跑一次 D。rj01 输入/输出 181,251/10,049，rj02 为 45,894/4,054，rj03 为 807,719/14,801，合计 1,063,768 token。三题仍为部分回答且未触及 token 限额；法规题达 128 次工具上限。
- 法规题正文有结构，未发布上年累计口径。但覆盖核验误撤回有《数据安全法》第三十一条支持的断言。前两题仍平铺回退，所需实验及版本对照交付物都不完整。人工预检 0/3。
- 旧错误诉诸历史口径作为现行输入的重放，240c75e 撤回错误并保留现行和历史对照。cd40d57 重放旧错误及误撤的受支持条文，模型给出可用反证但误填编号和缺口分组，框架未应用。d39274d 使用同一模型输出离线重放，修正反证编号后撤回旧错误，保留另外四条断言与两个缺口。两次模型重放合计 3,105 token。最新版暂无完整三题实跑。
- 正文与重放位于 `eval/results/research-judgment-rj*-hy4-240c75e-20261125-125613/`。正式对照评测未启动。

### 2026-11-25 | 研究提案回归

- 研究后端 205 通过。新增真实图回归验证一个拟用验收阈值经引用和语义核验后以建议发布；另一建议因虚构文献数字未进入语义核验和正文。相关契约 157 通过、1 跳过，仓库契约通过。

### 2026-11-25 | 缺证与待综合的路由回归

- 研究后端 206 通过，覆盖检索次数用完后仍按同一证据合成并发布拟用阈值，途中不再检索。相关契约 157 通过、1 跳过，仓库契约通过。

### 2026-11-25 | 覆盖核验的原文交接

- 研究后端 206 通过，综合回归同时验证覆盖核验实际收到全文范围及原文。相关契约 157 通过、1 跳过，仓库契约通过。

### 2026-11-25 | 实验方案格式回归

- 研究后端 206 通过，含项目建议、旧事实校验、两入口与补综合路线。相关契约 157 通过、1 跳过，仓库契约通过。

### 2026-11-25 | 单题端到端预检

- 按最新要求只运行 rj01，使用 hy4-flash-free。9aa16d5 使用 202,625 输入/19,028 输出，合计 221,653 token，发布 17 条明确标识的建议。69cc4de 使用 357,791/15,459，合计 373,250，达到 128 次工具上限；多个拟用阈值因写入事实格式被拒。
- 138c4d4 使用 195,225 输入/15,473 输出，合计 210,698 token，68 次工具调用，未触及 token 上限。发布同预算实验参数、300 题分层、配对置信区间和双向改判条件。存在配对执行与题目分配表述不一致，触发/停止与分支优先级也未形成一套可执行方案。人工预检仍未通过。
- 三份正文位于 `eval/results/research-judgment-rj01-hy4-{9aa16d5,69cc4de,138c4d4}-*/`。其他深度题和正式对照尚未启动。

## 2026-10-12 P4 改进轮（部分作答）与 OCR 收录流水线

| 范围 | 实际命令 | 结果 |
| --- | --- | --- |
| agent（+1：混合 claims 部分作答回归） | KE venv `agent/tests` | `32 passed` |
| 六目录 / researcher / 仓库契约 | 原命令 | `131 passed` / `141 passed` / 通过 |
| OCR 收录试跑（staging，不落库） | `ocr_text.py --doc-id zh_esign_2015 --out-dir /tmp/ocr_staging` | 4 页 4353 字符、零空白页、`text_source` 标记正确；正式补录待改进轮复测后（冻结件顺序纪律） |

行为变化：loop 对闸门结果逐条取舍——有通过 claims 即部分作答（答案由验证过的 claims 组成，`partial=True`，trace 记 `partial_answer`），全失败维持一次重生成→拒答；`check_corpus` 防篡改规则支持 `text_source=ocr` 双向约束。

## 2026-10-12 扫描件正式收录、round2 冻结件、mimo 对比与改进后评测

| 范围 | 实际命令 | 结果 |
| --- | --- | --- |
| OCR 正式收录 | `ocr_text.py --record` | 5 篇 42 页 / 48,997 字、零空白页；manifest 5 条 `text_source=ocr` |
| 语料 / 题目 / 仓库契约 | `check_corpus.py` / `validate_questions.py` / `check_repo_contracts.py` | 28 条完整 / 56 题全过 / 通过 |
| round2 冻结件 | `eval/baseline/round2.freeze.json` | 阈值/题目与 round1 逐字一致（自检断言）；DEFAULT_FREEZE 指向 round2 |
| 六目录（冻结件指针修复后） | 原命令 | `131 passed`（先前 1 红：测试拿 round1 校验新 manifest，属预期的换轮副作用） |
| mimo 对比（pre-improvement） | `round1.live.20261012-173406.json` | deepseek 全面占优（详见 decisions）；mimo C 条件 recall@10 塌到 0.2549、p95 84–88s |
| 改进后评测 ×2 | `--out eval/results/post_imp_deepseek` / `post_imp_mimo` | 后台执行中，完成后按 round2/round1 各自冻结门槛判定 |

## 2026-10-12 改进轮 v2：语义复检"实质回答"判据（修复 q042 型回归）

| 范围 | 实际命令 | 结果 |
| --- | --- | --- |
| v1 复测（deepseek，round1 语料） | `post_imp_deepseek/round1.live.20261012-174928.json` | 误拒 0.43/0.48/0.38→0.29/0.31/0.26 ✓方向对；**应拒正确 0.75/0.75/0.92→0.50/0.50/0.58 回归**（q042 型陷阱 9/9 误答）；机械分 0.37/0.39/0.39 |
| agent（+1：陷阱回归） | KE venv `agent/tests` | `33 passed` |
| 六目录 / researcher / 仓库契约 | 原命令 | `132 passed` / `141 passed` / 通过 |
| deepseek v2 复测 | `--out eval/results/post_imp_deepseek_v2` | 后台执行中 |

行为变化：语义复检判据 = ①被证据支撑 且 ②是对提问的实质回答（答非所问的正确陈述不收）；`CitationGate.verify`/`SemanticVerifier`/全部 checker 透传 `question`（可选参数向后兼容）。

| deepseek v2 复测 | `post_imp_deepseek_v2/round2.freeze.live.20261012-181106.json` | citation_acc 0.99/1.0/1.0；**应拒正确 A/B 回到 0.75**（C 0.667，q045 型残留 3–4/12）；**误拒回升 0.31/0.38/0.31**（判据变严的代价）；机械分 0.33/0.26/0.18。门槛：三条件仍卡 false_refusal + answer_mech，C 另卡 refusal_acc |
| mimo v1 复测（补充） | `post_imp_mimo/round1.live.20261012-185613.json` | 印证"mimo 不合拍"：A 应拒正确仅 0.33（陷阱漏得更多）、C recall 0.3/false_refusal 0.57、p95 55–98s、1 run error；不作为质量基线 |

## 2026-10-12 P4 归因修正 + 四连修 F1–F4（round3）

| 范围 | 实际命令 | 结果 |
| --- | --- | --- |
| 召回归因 | 逐金点排名分析 | 法条金点全在 top-5；0.7059 系评分结构性（外部金点题+跨语言页）；误拒 36/42 集中 q026/q028/q031/q038 |
| 四连修 | F1 闸门认登记身份 / F2 arxiv id_list+ti 查询 / F3 ID 加成 / F4 逐字引用 | 免新出站 |
| 测试（+4：身份数字对照、查询四形态、id_list 实发、ID 加成） | 全三套基线 | `136 passed` / `141 passed` / 通过 |
| round3 冻结件 | `eval/baseline/round3.freeze.json` | 阈值/题目/语料哈希与 round2 逐字一致（自检）；DEFAULT_FREEZE→round3 |
| deepseek v3 复测 | `--out eval/results/post_imp_deepseek_v3` | 后台执行中（报告将挂 round2 标签：指针切换与启动同刻，判定口径不受影响） |

## 2026-10-12 F5 scope 修复、追踪实跑、F6 Reader 保底（round4）

| 范围 | 实际命令 | 结果 |
| --- | --- | --- |
| v3 判定 | `post_imp_deepseek_v3` | 外部题被答 0–1/12、误拒 0.36/0.29/0.43、闸门失败 71/162——F1/F2 生效但未解锁 |
| F5 writer scope 如实标注（v1.3） | prompt 改 + round3 登记 | agent 34 绿 |
| v4 判定 | `post_imp_deepseek_v3→v4`（round3 标签） | 外部题被答仍 0–1/12、闸门失败 81/162——F5 仍未解锁 |
| **q026 单题追踪实跑** | 打印工具返回/writer/闸门 | **外部证据在 store 但 fuse top8 全 KB**（KB 第 10 名 RRF 0.0143 > 外部第 1 名 0.0115）→ writer 看不见论文证据 |
| F6 Reader 外部保底 3 席（v1.1） | `agent/reader.py` + 回归测试 | agent 35（+1）、六目录 137、researcher 141、契约全绿 |
| round4 冻结件 | `eval/baseline/round4.freeze.json` | 阈值/题目与 round3 逐字一致（自检）；DEFAULT_FREEZE→round4 |
| deepseek v5 复测 | `--out eval/results/post_imp_deepseek_v5` | 后台执行中 |

## 2026-10-12 v6/v7 终局判定（八轮迭代收官）

| 轮 | 报告 | B 条件误拒 | 机械分 A/B/C | 备注 |
| --- | --- | --- | --- | --- |
| v6（F7 全链） | `post_imp_deepseek_v6` | **0.214 ✅ 首个过线** | 0.23/0.27/0.18 | 外部题全解锁；A 误拒 0.405（结构 9+噪声 8） |
| v7（F8 temp0+逐字入答） | `post_imp_deepseek_v7` | 0.31（回退） | 0.18/0.25/0.17 | temp0 使 writer/verify 稳定保守，基础题被拒 |

八轮轨迹（B 误拒）：0.48→0.31→0.38→0.29→0.45→0.29→**0.214**→0.31；机械分恒 0.17–0.33。两项冻结规则边界待用户裁决（A 条件结构性分母、机械分逐字口径），见 decisions 2026-10-12 终局条目。测试终态：六目录 140、researcher 141、契约全绿。

## 2026-11-25 当前研究图文档复验

- 以 `9aa16d5` 为运行时代码基线。researcher 全套 206 通过，六目录契约 157 通过、1 跳过。仓库契约、走读链接和锚点、diff 空白检查均通过。
- README 的三段式离线对照命令完成 B、C、D 三条件的单次运行，安全样例通过。本轮未调用云模型。

## 2026-11-25 dev 合并回归

- researcher 216 通过，私库后端 101 通过、34 项按默认配置取消选择，六目录契约 207 通过、1 跳过。六目录回归使用了本地 arXiv 页缓存。
- 统一前端类型检查和构建通过，仓库契约和 diff 空白检查通过。当前三段式离线对照通过安全样例，历史 Agent 对照通过冻结语料和单题机械回归。本轮未运行云端质量评测。
