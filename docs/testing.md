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
