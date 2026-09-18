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

## 2026-09-18 目标升级与历史阶段保留

- 决定：经用户明确批准，直接规划工具调用式 Agentic RAG、Tavily/arXiv 来源扩展、PDF 切分与 OCR/图像识别增强；不再先交付只执行固定检索流水线的产品。保留两套原源码与独立进程，不重新生成式合并。
- 替代：2026-09-17 原设计的“单 Reader 固定流程”与“前端永久非目标”不再是目标约束；无界自主代理、多智能体辩论、多租户/多 KB 泛化、任意代码和通用表格结构解析仍不做。图像/图表文字和可核验视觉事实纳入范围，不承诺精密图表数值还原。
- 理由：用户希望私库、联网和论文搜索都由 Agent 按问题与结果决定调用，并增强 PDF/图像内容可用性；固定流水线与纯文本证据无法覆盖这一方向。
- 阶段：旧 P0–P2 与基线测试保持历史含义；新增 P0R，P3 拆成云模型、PDF/多模态、来源工具、Agentic/API/SSE 四个出口；P4 评测后才进入 P5。文档更新不表示供应商已选定或能力已实现。

## 2026-09-18 全云端模型与索引身份

- 决定：生成/规划/文本验证、embedding、reranker、OCR、vision 所有模型推理改用用户后续选择的云端 Adapter。根模板移除 `EMBEDDING_MODEL_PATH`、`RERANKER_MODEL_PATH` 和固定维度假设；每类配置 provider/model/version/base_url/api_key/timeout/retry，embedding 维度在选模型后明确。云 reranker 可显式禁用，只保留 RRF，不用本地模型 fallback。
- 替代：2026-09-17“embedding 迁移期沿用本地模型”目标失效；此前 torch/transformers/sentence-transformers 的测试环境和 96/47 个测试结果保留为历史回归事实，不是云端或干净安装验收。旧子项目的实现与模板仍待 P3a 迁移，本轮不改依赖或安装环境。
- 理由：用户不希望在本机部署推理模型或维护权重/GPU；各云能力协议未必兼容 OpenAI，因此由明确 Adapter 处理，而非声称填写任何 base URL 即可运行。
- 索引规则：查询与入库 embedding 身份含 provider、实际模型/部署版本、维度、归一化/预处理版本；新建/replace/reindex 都必须保留。更换模型重建新 collection 验证后切换并可回滚；OCR/vision 或切分版本更换需要重解析，而非只重嵌入。

## 2026-09-18 Agentic 工具循环与确定性对照

- 决定：由一个受限编排 Agent 规划、拆问、重写、选源并根据证据缺口追加检索；KB 本身是确定性工具，不再嵌套无界 Agent。Planner/Reader/Writer/文本 Verifier 默认共享 `LLM_*` 云配置。
- 默认：最多 3 轮、12 次工具调用（含 retry/fetch/read）、累计 20000 模型 token、180 秒总 deadline、并发 4；可选美元预算需要有效计价/估算。未知用量不报 0，启用费用硬上限但无法估算时拒绝启动付费任务。
- 理由：让规划与检索策略可学习/可评测，同时防止成本失控、重复检索和无证据循环。工具必须白名单/schema 校验、调用关联 ID、循环检测、取消及预算预留；原文中的指令不能越权改变系统行为。
- 保留：RRF k=60、KB/外部权重 1.0/0.7、top-8 是 Reader 排名算法和 fixed 对照，不是 Agent 必须固定调用所有来源；云 rerank 放融合后，失败保留 RRF。重复同 provider/channel 查询先合并去重，不反复累计独立票数；引用失败最多重生成一次且不重置预算。

## 2026-09-18 Source Registry 与 arXiv 首批扩源

- 决定：KB、Tavily、arXiv 都纳入首批来源，统一 Source Adapter 和 Evidence，新增 provider 不修改核心 Agent；登记的来源才可 fetch/read。arXiv 官方元数据接口无需 API key，遵守节流/缓存并记录 ID、版本、可用 DOI、摘要/全文范围。
- 理由：研究问题需要论文证据而非仅一般 Web；一个插件入口不等于已支持 arXiv，必须有具体 Adapter 与行为测试。摘要可用于摘要范围内结论，全文断言必须获取对应版本正文，失败不能冒用摘要。
- 去重与安全：跨 Tavily/arXiv 同论文合并保留发现 provenance，不同版本不误并；规范 URL 与版本/内容 hash 贯通。单源失败返回结构化空证据/错误，不静默生成 example.com mock。受控 fetch 限制 URL/MIME/大小/重定向并逐跳防 SSRF，工具结果视为不可信数据。

## 2026-09-18 多模态原资产、PDF 切分与引用裁决

- 决定：Evidence 保持单一结构，增加 paper/asset 来源、modality、doc/version/page/block/region/bbox/asset、提取/模型/处理版本与内容 hash；OCR 转录、视觉观察、视觉推断独立标记，纯图片可没有 raw_text。
- 替代：文本 raw_text 不再是所有模态的唯一裁决依据；它仍是文本断言的定位依据，但 OCR 歧义与图像结论要回看原资产/区域验证。视觉描述不能回填成 PDF 原文，也不能只用同模型的文字输出自证。
- 理由：现有逐页纯文本/粗页范围不足以承载扫描件、多栏、图注/图片关联和可靠区域引用。保留法规/标题 parent-child 切分并加入论文/图注关联；元数据必须经 parser/cleaner/chunker/index 到 citation 全程贯通。
- 入库：原生文本可本地非模型提取/渲染；OCR/vision 均云端处理。保留 Celery worker/beat，加长调用心跳、租约 fencing、幂等及孤立索引清理；所需页/模态失败不发布完整版本。

## 2026-09-18 云数据出站及前端配置

- 决定：本机存储不等于数据全留本机。查询/文本送 embedding/LLM，PDF 页/图像送 OCR/vision；默认 `CLOUD_DATA_UPLOAD_ALLOWED=false`，用户核对各 provider 的地域、留存与费用后授权，凭证配置不等于授权上传。地域/留存说明只是用户记录，不保证或改变第三方政策。
- 理由：全云模型是用户选择的能力路径，但私库/图像出站必须可见、受控；本轮不实际发送内容到云端。
- P5 配置：前端可设置云 provider/model/base_url/key 和受控运行时参数；环境/Compose 管启动基础设施与加密主密钥。凭证后端加密、GET 只返 configured/source，不进 localStorage/日志/SSE；候选验证失败保留旧配置，运行时覆盖可删除以恢复环境值。embedding 保存后必须执行索引迁移。
- 前端范围：两套旧前端继续为过渡资产，P5 统一界面提供页/区域/图片定位及工具状态，替代验收后才删除旧资产。不暴露隐私推理，不把未通过闸门的 token 当最终回答。

## 2026-09-18 新验收与测试分层

- 决定：旧测试、旧前端构建、gitleaks 保留为回归门槛，但不能证明云协议、Agentic、多模态或索引迁移完成；P3 新增 fake/脱敏 recorded 契约、真实 graph/executor、页/区域 fixture 与失败矩阵测试。普通 PR 不依赖真实云凭证、付费服务，也不新增 lint/格式门禁。
- 评测：保留 KB-only/external-only/fixed 混合，增加同源同模型同预算的 Agentic、去 arXiv/去 OCR-vision/禁追加检索/去 rerank 消融；记录 OCR/视觉/页区域质量、来源覆盖、工具终止合规、token/费用、p95 延迟。Recall@10/20 在 top-8 截断前计算。
- 替代与理由：2026-09-17“融合五项指标均不低于每个单源”门槛不再适用；在正式跑分前冻结非回归容差、分层质量及成本/延迟门槛与人工标注，不能先看结果再放宽。安全拒绝样例必须全部通过，不以平均质量掩盖越权/伪证据/无限循环。
- 保留缺口：34 个旧 integration 与真实 GitHub PR CI 仍未验证；真实云 smoke 需单独授权的样本、预算与凭证。文档更新不替这些结果做完成声明。
- 本轮核验：仅规划/根模板/约束文档有 diff，三个占位 README 同步新的阶段与章节引用；64 个根变量唯一且所有云 API key 为空，阶段前置/验收与本地模型路径移除检查通过。旧回归为 KB 96 passed/34 deselected、researcher 47 passed；改动文件的 gitleaks 扫描无泄漏，未改业务代码、未装依赖、未提交/推送、未发送私库到云端。

## 2026-09-18 文档复核补强：出站身份与配置密钥

- 决定：总出站开关之外增加 `CLOUD_DATA_APPROVALS_JSON`，逐能力绑定 provider/endpoint/model/version 及地域/留存声明的 fingerprint；云 rerank、Tavily/arXiv 查询和远程 fetch 与模型上传同受门禁。开关关闭、授权缺失/不匹配不发第三方用户数据请求，新配置使旧授权失效。
- 理由：只用全局布尔值会遗漏外部搜索及候选文本外送，且供应商切换后可能把旧同意错误沿用；静态模板 default=false 并不证明现有应用已阻断出站，实际行为在 P3a/P5 测试。
- 凭证与 endpoint：云 endpoint 限受信 HTTPS，配置验证和保存须执行访问策略；密钥只发绑定主机，不随跨 host 重定向。密钥持久化要求有效强主密钥，缺失/弱/格式不符拒绝保存，轮换失败保留旧密文，禁止明文/临时密钥 fallback。
- 指标：设计、路线图、eval 占位统一采用引用准确率、拒答准确率、答案正确率与误拒率，并明确人工金标准裁决；不使用未定义的“答案质量”作为验收指标。

## 2026-09-18 评测语料与人工题目集（P4 前置交付）

- 决定：新建 `eval/corpus/`（28 篇：16 中国法律法规 + 2 NIST SP/AI RMF + 3 RFC + 7 arXiv，其中网络安全法 2016/2025/修改决定三件套与论文 2304.09848 v1/v2 作版本对照）与 `eval/questions/questions.v1.jsonl`（56 题全部 `verified:false`），配 `download_corpus.py`（幂等、节流、重定向/大小受限、flk 三步链路）与 `extract_text.py`（PyMuPDF 页级镜像 + 文本层统计）。不实现 runner、不调用云模型、未跑评测；`knowledge_engine/`、`researcher/` 零改动（仅读用其 `.venv` 的 PyMuPDF）。
- 事实记录：flk.npc.gov.cn 新版为 Vue SPA，API 为 `POST /law-search/search/list`（请求体含 `orderByParam` 会 500，须省略）→ `GET /law-search/search/flfgDetails?bbbs=` → `GET /law-search/download/pc?format=pdf&bbbs=&fileId=` 返回 1 小时预签名 S3 地址；rfc-editor.org 的 `rfcXXXX.pdf` 已 404、datatracker PDF 需登录，故 RFC 按规范格式 `.txt` 收录（换页符分页、`[Page N]` 页码天然保留）；arXiv Atom 元数据未声明 license → 7 篇一律 `redistributable:false, in_repo:false`（PDF 与镜像 gitignore，可由脚本重建）。
- 5 篇扫描件（zh_cybersec_2016/zh_esign_2015/zh_ecom_2018/zh_antimon_2007/zh_puborder_2012，每页一张 2480×3484 JPEG、零字体、`blank_page_ratio=100%`）：按任务纪律**保留 + 标记 `text_layer_ok=false`**，未擅自剔除；版本对照题改由《修改决定》（文本版）+2025 修正版支撑。`knowledge_engine/Data/` 的 2016 版文本型 PDF 因来源 URL 不可复现而未采用，仅记录为备选。CII 条例、网络数据安全管理条例、商用密码管理条例（现行）因 flk 仅 Word/OFD 无 PDF 而"未能获取"（如实列入报告，不顶替）；GB/T 0 篇待用户决定。
- 题目纪律：56 题中 48 题的 `required_points` 由构建脚本从页文本**机械提取**（空白折叠保留连字符断词/ﬂ 连字/全角数字），`validate_questions.py` 离线复核逐字命中；8 道 external_only 的外部事实（arXiv 摘要、RFC 5246 标题、CAC 施行日期、flk CII 条例施行日、Qdrant 端口）构建时经 API/WebFetch 核对并注明需人工复核；forbidden 与 required 的冲突定义为"forbidden 是 required 的子串"（q037 因此清空 forbidden，避免评分误伤）。
- 本轮核验：28/28 下载成功、sha256 回写后幂等重跑全部 skip；56/56 题过校验、配额 15/10/8/5/12/6 达标、verified=true 为 0；未提交、未推送、未发送任何内容到云端。

## 2026-09-18 评测语料验收与归属定案

- 验收方式：**独立复核**而非重跑交付方校验器——自算 sha256、自统计页数与空页比、自写归一化匹配（去空白 + 连字符接合）在全语料定位 `required_points` 后再与声称 locator 比对。结论：sha256 28/28 匹配、页数 28/28 一致、`in_repo` 标志与 gitignore 零矛盾、79 个 required_points 中 68 个在声称文档且页码有交集、**0 个页码错**、未命中 9 点**全部属于 external_only**（离线不可复核，与交付方声明一致）、**0 道题依赖扫描件**、`knowledge_engine/` 与 `researcher/` 零改动、未提交、改动文件 gitleaks 无泄漏。交付物机械部分**通过**。
- 扫描件定案：5 篇零文本层件**保留在 manifest（`text_layer_ok=false` 即机器可读判据），但不进入首版入库/检索语料**；其真正用途是 P3b 云 OCR 的验收 fixture，届时再纳入入库。不新增冗余字段。
- 体积定案：入库 21 个 PDF 实测 37.9MB + 页镜像 1.17MB + 脚本 0.13MB，**接受入库**——属自建评测证据而非生成物；arXiv 7 篇 PDF（14MB）与页镜像继续忽略（许可未声明）。
- 收录范围定案：放弃《关键信息基础设施安全保护条例》《网络数据安全管理条例》《商用密码管理条例（2023 现行版）》——flk 无 PDF；其"私库没有、必须联网"的对照价值已由 q032 等 external_only 题承担，补 HTML 版反而削弱对照。GB/T 国家标准维持 0 篇。
- 剩余验收关卡：56 题 `verified` 全为 false，**须用户人工核对后方可作为正式金标准**，优先 8 道 external_only（外部内容会变）与 12 道 insufficient（拒答理由是否成立）；48 道语料内题已由独立脚本验证逐字可溯源。

## 2026-09-18 验收新发现：三项 P3d/P4 设计输入

- **全角数字会造成假拒答（高优先级）**：28 篇中 9 篇为人大公报版全角数字，数据安全法施行日期仅以 `２０２１年９月１日` 存在、无半角形态。引用闸门的机检必须做全角/半角归一化，否则真实存在的证据会被判"不支持"，直接打击"缺证才拒答"的可信度。当前无题目受影响（含数字的点均为 external_only）。
- **参考文献列表会造成假命中**：q030 的 `required_points` 字符串实际出现在其他 RFC 的参考文献区（rfc_6749 p69、rfc_8446 p116–117）。P4 评分规则须明确：参考文献列表中的字符串**不计入来源覆盖**。
- **跨页引用是常态**：q015 要点跨 1–2 页、q037 跨 2–3 页。页引用准确率须按"**页码有交集**"判定，按页号完全相等会系统性低估。

## 2026-09-18 仓库转公开前的历史改写：剔除个人材料

- 决定：仓库定位为**公开**（作品集项目），因此在首次推送前**改写历史**剔除 51 个个人学习/面试材料文件——`researcher/project_course/`（23）、`knowledge_engine/Teach_Learn/`（22）、`researcher/project_interview_guide.html`、`researcher/docs/interview-study-guide.html`、`knowledge_engine/Doc/` 下 4 份学习/面试 HTML——而不是只做 `git rm --cached`。
- 理由：`.gitignore` 对**已跟踪**文件完全无效；只 untrack 会让文件继续留在 `e23e645` 中，推送后仍可被 `git log --all` 翻出。三个提交都未推送，改写零协作风险，是唯一能实现"从未存在过"的时机；推送后再删无法回收（缓存、fork、存档抓取）。
- 执行与风险：用 `git filter-branch --index-filter`（`git-filter-repo` 未安装）改写 `251e0d1..HEAD`。改写前把 51 个文件打包备份到**仓库外** `../ProvenanceResearch-personal-material-2026-09-18.tar.gz`；filter-branch 同步工作区时确实把这 51 个文件从磁盘删除，已从备份恢复并逐字节校验 sha256（51/51 一致）。随后删除 `refs/original`、`backup/pre-personal-rewrite`，并 `reflog expire + gc --prune=now` 清除不可达对象。
- 防回归：根 `.gitignore` 增加这些路径规则（另加 `.zcode/` 本地工具状态）；`knowledge_engine/README.md` 删除指向被移除文件的 3 条链接，避免死链。
- 范围边界：`researcher/1.md`、`new.md`（标注为历史问题记录的工程文档）与 `knowledge_engine/Aim/`（项目阶段计划）不属于个人材料，**保留**。"移出"不等于"删干净"，只针对学习/面试类材料。
- 影响：提交哈希已变，`main` 现为 `251e0d1 → c50b874 → e33451b → bd33025`；远端仍停在 `251e0d1`，故推送是 **fast-forward，无需 force push**。51 个文件仍在本地磁盘，只是不入库。
- 核验：这些路径在全部历史中 **0 条记录、0 个对象**；51 个文件磁盘仍在且被正确忽略；KE `96 passed / 34 deselected`、researcher `47 passed`。

## 2026-09-18 CI 第三类作业：仓库契约（保护"证据"）

- 决定：CI 新增 `repo-contracts` 作业，包含三项——`eval/corpus/check_corpus.py`（新增）、`eval/questions/validate_questions.py`（既有）、`scripts/check_repo_contracts.py`（新增）。新增 `scripts/` 为第七个顶层目录，用于仓库级校验脚本。
- 理由：作品集的展示材料是**截图 + 指标页 + 代码**，其可信度全部建立在"语料与题集没被改坏、配置模板不含真实密钥、阶段验收齐全"之上。这类失效单元测试查不出来（本仓库已被"文档互相矛盾"咬过两次），但会直接毁掉面试时的可信度。
- 合规防线（新增脚本的核心）：`in_repo=true` 的文件若被 gitignore 忽略、或 `redistributable=false` 的文件未被忽略，一律失败——即**不可再分发内容被推送前必须被拦下**。同时校验 manifest 的 sha256、页数、以及 `text_layer_ok` 与实测空页比例是否自洽。
- 契约检查范围：配置模板（本地模型路径不得回归、密钥必须留空、五类云能力字段齐全、出站默认关闭且授权映射为空、预算为正整数）；路线图每个阶段必须有目标/前置/验收；Markdown 链接与锚点可达；`docs/decisions.md` 必须以 HEAD 版本为前缀（防历史被改写）；凭证、运行时配置库、`.zcode/`、个人材料必须处于忽略状态。
- 刻意不做：不引入 ruff/mypy/格式门禁，不扫描两个子项目的历史文档链接（避免对旧内容施加新门禁而逼出例外清单）。链接检查只覆盖本仓库自撰的 12 份文档。
- 验证：三个脚本本地全部通过（Python 3.9 与 3.13 双口径），并做了负向测试——把 arXiv 条目的 `in_repo` 改为 `true` 后脚本立即报出误发布风险，证明防线不是摆设。作业为纯标准库、不联网、不需要任何 secret，因此 PR 上可安全常开。
