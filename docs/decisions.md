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

## 2026-09-18 gitleaks 允许清单：公开标准文档中的示例凭证

- 事实：首次全历史扫描在提交语料后报出 **15 处 `generic-api-key` 命中，全部来自 `eval/corpus/pdf/rfc_6749.txt` 与其页镜像**。核实后确认是 RFC 6749（OAuth 2.0）规范原文自带的示例值——该 RFC 在示例授权流程中印有 refresh_token / client_secret / access_token / client_id 四个示例凭证，原文均以 "For example" 引出，属公开发布的示例，**不是真实凭证**。（此处刻意不复写这些值：一旦抄进文档就会再次触发扫描，见下方"验证"。）
- 决定：新增根 `.gitleaks.toml`，`[extend] useDefault = true` 保留完整默认规则集，仅对 `eval/corpus/pdf/rfc_6749.txt` 与 `eval/corpus/text/rfc_6749.pages.jsonl` 两个路径、且仅对 `generic-api-key` 一条规则放行。
- 理由：全局关闭规则或整目录放行会让真实凭证藏进语料时被一并放过；作用域收窄到"规则 + 文件"后，其他规则与其他文件照常扫描。
- 验证：配置生效后全历史扫描 `no leaks found`；两次注入测试确认清单足够窄——在语料外注入假 key、以及在语料目录内非 RFC 6749 的文件注入，**都被正常报出**。工作区扫描剩余 4 处命中全部位于 `researcher/deep_research_system/.env`（真实凭证、已被忽略、永不推送），已提交内容为零命中。
- 附带确认：CI 的 gitleaks-action 读取仓库根 `.gitleaks.toml`，因此该清单同时作用于本地与 CI。

## 2026-09-18 首次 CI 运行的两个失败与修复

- 背景：首次推送触发 CI（run #1），6 个作业中 **4 个通过**（knowledge_engine 干净安装测试、researcher 测试、两套前端构建），**2 个失败**。以下是失败原因与处置。
- **失败一：题集校验在 CI 失败（q015/q022/q024/q038）**。原因：`validate_questions.py` 对"页级镜像缺失"**无条件报错**，而这 4 题依赖 arXiv 语料，该语料因许可未声明 `in_repo=false`、不随仓库发布——CI 中必然缺失。这是校验器的真实缺陷：它没区分"资产本就不发布"与"资产意外丢失"。
- 处置（校验器语义修正）：`in_repo=true` 却缺镜像 → 仍报错；`in_repo=false` 缺镜像 → 记为**跳过**并在汇总显式列出（CI 下 4 题、附原因与本地补齐命令），本地有缓存时零跳过、完整核对。附带修正一处归因缺陷：`required_points` 与 locator 并非一一对应，只要该题有一处定位页未发布，就整题跳过逐字核对，避免用残缺文本误报失败。
- **失败二：gitleaks 报出泄漏**，而同一提交在本地（8.30.1 + 同一份 `.gitleaks.toml`）为 **0 命中**。判断是 `gitleaks/gitleaks-action@v2` 自带二进制版本较旧，不识别 `[[allowlists]]` 清单 schema，导致允许清单被静默忽略。
- 处置：改用**固定版本 CLI**——CI 内下载 `gitleaks_8.30.1_linux_x64.tar.gz`（资产名经 GitHub API 核实）并执行 `gitleaks git . --redact --no-banner --config .gitleaks.toml`，与本地验证逐字一致；同时消除 license 与 action 权限的不确定性。
- 教训（写入 `docs/roadmap.md` 同义）：**"本地绿"不等于"CI 绿"**——差异来源正是"仓库里没有的东西"（被 gitignore 的资产、action 自带二进制的版本）。这正是首次运行 CI 的价值：它把"我以为验证过"变成"确实验证过"。

## 2026-09-22 架构拷问：部署边界定为单机单 researcher + KE 多进程

- 决定：researcher（DRS）保持单实例；knowledge_engine worker 以 Celery 多进程（prefork）为默认形态；「researcher 多实例 / 多机水平扩展」记为**非目标**，与 design §11 多租户非目标一致。不建分布式限流、分布式锁、跨实例熔断状态共享；arXiv 3 秒间隔用 DRS 单进程 semaphore 落实。
- 理由：产品是本机单用户自托管（design §1）；KE 多进程并发正确性已由 PG fencing（`SKIP LOCKED` + advisory lock + fencing token）零成本保障；researcher 水平扩展需把 `_tasks/_running/_subscribers/取消句柄` 全部内存态外移（等于重写任务执行层），并推翻 P3d「旧任务生命周期与 SSE 回归保持」前置约束，单用户下收益为零。KE 多容器与多进程的实际差距小（P3b 做完心跳/孤立点清理后只差存储层），故多容器维度也暂不承诺。
- 已知接受的代价：DRS 进程死亡 → 在跑任务死亡，重启清孤儿（RUNNING→FAILED）不恢复；是否补恢复机制随扩展功能处置（审计 Q7，待确认）。
- 过程：本轮为交互式架构拷问（grilling），33 项发现与逐题记录见 `docs/architecture-audit.md`。

## 2026-09-22 KE 任务投递语义：at-least-once + 双队列，恢复与计时器心跳捆绑

- 决定（记为 P3b 落实时的既定设计，本轮零代码改动）：`task_acks_late=True` + `task_reject_on_worker_lost=True`；拆 `ingest`（重）与 `control`（recovery/reindex，轻）双队列；`TASK_AUTO_RECOVER_PROCESSING` 的开启与 P3b「计时器心跳」**捆绑交付**——心跳先行，之后 PROCESSING 过时任务才改为重派（fencing 防旧 worker 发布），落地前维持 fail-fast。
- 理由：现状 `task_acks_late=False` 意味着硬杀即丢消息，崩溃 = 任务判死 + 已发生的云 OCR/embedding 费用白烧；而 claim/fencing 体系本就为幂等重派设计，at-least-once 几乎免费。唯一风险是现心跳为「阶段间调用」：活着的长阶段任务与死任务不可区分，提前开自动恢复会双跑双花（P3b 引入长云调用后风险翻倍），故恢复必须等计时器心跳。双队列防 recovery 扫描被长 ingest 堵死。
- 验收（P3b 时）：硬杀 worker 不丢消息；重派幂等；旧 worker 失去租约后不能发布版本；PROCESSING 自动恢复仅在计时器心跳落地后开启。

## 2026-09-23 目标架构图拆分为系统拓扑与 Agentic 运行时控制流

- 问题：原 `architecture-target.drawio` 把 `Agentic 有界循环` 压缩成单个组件，连线主要表达服务之间的调用关系，视觉上容易被误读为固定的 `检索 → 融合 → 生成` 流水线，无法证明目标结构具有 Agentic RAG 的观察与重规划闭环。
- 决定：保留 `architecture-target.drawio`，明确其职责为**目标系统拓扑图**；新增 `architecture-target-agentic-rag-runtime.drawio`，专门表达 Planner 每轮依据 Question、Observations、Evidence gaps 与剩余预算动态选择 `0..N` 个工具或停止，以及 `ToolResult → Evidence → 充分性判断 → OBSERVE → 重规划` 的反馈回路。
- 边界：Agent 只决定下一动作；工具白名单、JSON Schema、出站授权、预算、deadline、取消、RRF、引用验证和终止原因仍由确定性代码执行。工具顺序不写死，但循环有界，不把“Agentic”解释成任意工具、任意网络访问或无界自治。
- 理由：部署拓扑和运行时决策循环回答不同问题，强行合成一图会掩盖最关键的控制流。分图后既能看清两套进程及基础设施边界，也能直接看到 Agentic 与固定 RAG 的结构分界。
- 状态：本条只修正文档表达，不代表 P3d 已实现；实现验收仍以 `docs/roadmap.md` 的 fake LLM 驱动真实 graph、追加检索、停止、预算与引用闸门测试为准。

## 2026-10-10 采纳 P3-P5 重排版执行计划（新增 P2.5 与硬化轮，P3b 后移）

- 决定：以用户批准的《下一阶段迭代计划（P3-P5 重排版）》（`docs/execution-plan.md`）作为下一轮执行顺序：**P2.5 安全修复 → P3a Core Adapter → P3c 文本工具 → P3d Agentic+引用闸门+SSE → P4 评测 → P5 Demo UI → P3b OCR/Vision → 硬化轮**。相对原 roadmap 的变化：新增 P2.5（安全与基础修复）与硬化轮（JWT/限流/观测/Compose）两个阶段；P3c 改为文本先行、不再以 P3b 溯源稳定为前置（Evidence v2 的 bbox 字段留空占位）；P4 提前到 P5 之前并先用 15–20 个代表问题建立 baseline；P3b 多模态后移到 P5 之后。
- 保留：P0–P5 各阶段的能力目标与验收标准不放松；Agent 预算默认值（3 轮/12 次工具/20000 token/180s）、RRF k=60 与 top-8、全云模型契约、出站双闸、"mock 仅限测试"均不变。
- 理由：优先造出"提问→检索→证据→引用/拒答"的完整文本闭环（Vertical Slice），避免先陷入 P3b 多模态泥潭；前半段完成到 P4/P5 第一版即达到作品集展示水平，OCR/Vision 与硬化属后续提升。执行节奏改为**每完成一小部分即提交一次 git**（用户 2026-10-10 要求）。
- 顺序裁决：计划正文 Phase 5/6 编号（P3b 在 P5 前）与其"执行优先级总结"及结尾段落（P5 在 P3b 前）不一致，按总结与结尾段落取 **P5 先于 P3b**，已在 `docs/execution-plan.md` 文首标注。

## 2026-10-10 P2.5-0.1 模型测试接口 SSRF 防护（provider/host 精确 allowlist）

- 决定：`POST /models/test` 在任何出站请求之前调用 `app/model_pool/endpoint_guard.validate_model_endpoint`：provider 必须在注册表（deepseek/zhipu/kimi/doubao/ernie/qwen/openai/anthropic），api_base 仅允许 https、禁止 URL userinfo、端口仅 443/默认，主机必须**精确**命中该 provider 的官方主机（不做后缀通配）；localhost、私网 IP、IP 字面量（含公网 IP）、file:// 一律拒绝；httpx 显式 `follow_redirects=False`（密钥不跨重定向发送）。请求体新增可选 `provider` 字段，为空时按主机反查，反查不到即拒绝。
- 替代：原实现直接把用户提交的 `api_base` 拼上 `/chat/completions` 出站，等于服务端任意 URL 请求代理（可探内网/metadata），且 api_key 随之外送。
- 理由：公开仓库的模型测试接口是最容易被指出的可信度缺口；"精确主机 allowlist + scheme 收紧"比黑名单式 IP 过滤更难绕过（DNS rebinding 对精确主机名无效）。自定义代理/自建端点暂不支持，待 P5 前端配置有出站授权后按 `CLOUD_DATA_APPROVALS_JSON` fingerprint 机制放开。
- 验收：新增 `tests/test_endpoint_guard.py`——localhost/127.0.0.1/10.x/192.168.x/172.16.x/169.254.169.254/IP 字面量/file:///http/非允许 provider/userinfo 伪装/非 443 端口全部拒绝；路由级断言非法目标不发起任何出站请求（monkeypatch httpx 为断言失败）。researcher 65 passed（47 基线 + 18 新增）。

## 2026-10-10 P2.5-0.2 删除 fake success：统一 ProviderUnavailableError

- 决定：删除两处伪造成功路径——researcher `SearchService` 在缺 TAVILY_API_KEY 或 Tavily 调用失败时不再返回 `example.com` mock 结果（连同 `last_mode`/`search_mode="mock"` 机制一并删除，schema 默认值改 "real"）；KE `AnswerGenerator` 在 LLM 失败/输出非 JSON 时不再回退本地抽取答案（`_generate_deterministic` 及其孤儿 helper 一并删除），KE query API 将 `ProviderUnavailableError` 映射为 503 `provider_unavailable`。统一由 `ProviderUnavailableError` 上抛，retry/fallback/refusal 留给上层（P3d 引入）。
- 替代：原行为把"provider 挂了"伪装成"搜到了 3 条结果/生成了有据答案"，直接污染 provenance 链条与评测基线——这是公开仓库可信度的最大污点。
- 理由：Evidence-grounded 系统的前提是证据为真；mock 结果与本地抽取答案都属于无 provenance 的伪证据。AGENTS.md 已有"缺云配置显式失败、不得静默降级"约束，本轮把生产路径落实到该约束。eval 逐条已有 try/except 记录 error_message，异常传播语义正确。
- 测试迁移记录：KE `test_answer_generator` 原第 2 例断言本地抽取答案（"基于当前检索到的资料"），正是要删除的行为——改写为 4 例：无证据拒答不变、LLM 失败抛 `ProviderUnavailableError`、stub LLM 走真实生成路径、LLM 输出非 JSON 抛异常。researcher 新增 `test_search_service` 3 例（缺 key/调用失败抛异常、成功返回真实结果且无 mock URL）。
- 验收：KE 98 passed（原 96 + 测试改写净增 2）、researcher 68 passed（原 47 基线 + 0.1 的 18 + 本轮 3）；两套基线原有行为测试未被破坏。

## 2026-10-10 P2.5-0.3 key/端点严格绑定（provider → capability → key pool）

- 决定：三处"跨 slot 找任意配置"全部删除——`APIKeyPool.get_api_key` 不再兜底扫 `MODEL_*_API_KEY`（无自身绑定 key 即返回 None）；`router._has_api_key` 只认 models.yaml 为该模型登记的 key env（其他 provider 的 key 不能让本模型显得可用）；`LLMClient._resolve_base_url` 不再兜底扫 `MODEL_*_API_BASE`（否则会把 A 模型的 key 发往 B slot 的端点），缺失时只回退本 provider 官方默认 base，仍无则抛 `ProviderUnavailableError`。
- 替代：原兜底链（任意 slot key → 任意 slot base）意味着密钥可被发往非绑定主机，且路由会把"别的 provider 有 key"误判为本模型可用——与"密钥只发绑定主机"（2026-09-18）直接冲突。
- 理由：key routing 的可信度建立在"谁的 key 只走谁的端点"上；宽松兜底让 SSRF 修复（0.1）形同虚设（合法 host 校验过了，但 key 可以搭错车）。显式失败（None/异常）交给上层处理，与 0.2 的 ProviderUnavailableError 语义一致。
- 测试迁移记录：新增 `tests/test_key_binding.py` 6 例——自身 key 缺失时返回 None 而非他 slot key、只用自身绑定 key、路由可用性忽略他 slot key、端点解析永不取他 slot base、优先自身绑定、全无绑定时抛异常。原有 key_pool/router 测试未改动（断言的都是本就正确的行为）。
- 验收：researcher 74 passed（47 基线 + 0.1 的 18 + 0.2 的 3 + 本轮 6）。

## 2026-10-10 P3a：providers 云适配层（一真一假 + 错误六分类 + EmbeddingIdentity）

- 决定：新增顶层 `providers/` 包作为所有 AI 能力的统一云接口——`errors.py` 定义六类稳定错误码（CONFIG_MISSING/AUTH_FAILED/RATE_LIMIT/SERVER_ERROR/TIMEOUT/INVALID_RESPONSE）与 `ProviderError`（携带 retryable），上层只按错误码决策；`llm/` 落地统一 `generate(messages, metadata)` 协议 + **一个真实 provider（DeepSeek，OpenAI 兼容）+ 一个 fake provider**（脚本化，仅限测试）；`embedding/` 落地 `EmbeddingIdentity`（provider/model/dimension/preprocess_version 四元组）与 `CollectionBinding`（一个 collection 只属一个 identity，改绑/越权访问拒绝）；`reranker/`、`ocr/`、`vision/` 只建接口位，实现随 P3c/P3b 接入。
- 实现取舍：DeepSeek adapter 完整实现 timeout/429/5xx/timeout 重试（指数退避）与响应结构校验；`httpx.MockTransport` 做 fake 传输，契约测试无凭证、不联网。api_key 只发配置绑定 host、禁重定向、base_url 强制 https（延续 P2.5 与 2026-09-18 出站纪律）。真实云 smoke 照旧不进普通 PR。
- 替代：原两套系统各自裸 httpx 调用（researcher `LLMClient`、KE `LLMService`），错误语义不一致且无统一分类；它们暂保留为旧路径，接入迁移在后续阶段进行，本轮零业务代码改动。
- 理由：P3c 的工具与 P3d 的 Agent 都要按"错误类别"决定 retry/fallback/refusal，没有稳定错误码就只能解析各家错误文本；EmbeddingIdentity 提前立住是为了索引迁移/回滚（换模型必换 collection）从第一天就有可测契约。
- 验收：`providers/tests/` 25 例全绿——401/403→AUTH_FAILED 且不重试、429→RATE_LIMIT 重试至成功或耗尽、5xx→SERVER_ERROR 重试、timeout→TIMEOUT 重试、malformed response（坏 JSON/空 choices/缺 content/非字符串 content）→INVALID_RESPONSE 且不重试、缺配置零出站、http base_url 拒绝、密钥只发绑定 host；identity 四元组校验、维度不符拒绝、collection 改绑/越权拒绝、fake embedding 确定性。CI 新增 `providers-tests` 作业（httpx+pytest 钉版，无 secret）。

## 2026-10-10 P3c-text：Evidence Schema v2 + Source Registry + 五工具文本链路

- 决定：新增顶层 `evidence/` 与 `tools/` 两包落地文本世界工具链。`evidence/schema.py` 实现 design.md §2 的 Evidence v2（schema_version=2；source_type=kb_chunk/web/paper/asset；modality；provenance 按类型必填——KB 要 doc/version/chunk/index、web 要 canonical_url+fetched_at、paper 要 arxiv_id+明确版本；locator 支持 page/chunk/url/section，bbox/artifact/region/asset 为 P3b 占位但形状已校验；content_scope=snippet/abstract/fulltext/region 且 fulltext 禁止空正文——摘要不得冒充全文；citation_id 前缀 K/W/A/I，由完整来源身份+版本+位置+内容 hash 生成）。`evidence/registry.py` 按 design.md §3 去重：论文 arxiv_id+版本（不同版本永不合并）、KB doc/version/chunk、web 规范 URL+内容 hash；Tavily 与 arXiv 同时命中同一论文合并为同一 Source 但保留两条发现 provenance；ProviderRegistry 维护能力/启用/凭证/健康/限额。`evidence/store.py` 的 EvidenceStore 校验 citation_id 与内容一致、同 id 异内容拒绝覆盖，并提供 resolve_citations 供引用闸门使用。
- 工具契约：按 design.md §3 返回 `call_id/status/evidence/meta/error`（status=ok/empty/error，error 脱敏+稳定 code+retryable）。五工具全部落地——`kb_search`（内部 HTTP 调 KB、固定内部地址、带 doc/version/chunk/index 身份）、`web_search`（首批 Tavily、provider 是注册值、带 URL/fetched_at）、`arxiv_search`（官方元数据接口无 API key、记录 ID/版本、摘要范围 abstract、默认 3 秒节流可注入时钟）、`source_fetch`（只接受已登记 source_id、逐跳 SSRF 校验+大小/MIME/重定向上限、成功才标 fulltext）、`evidence_read`（只回已登记 evidence_id，不读任意本地路径）。ToolExecutor 做工具名白名单与参数白名单校验，单工具崩溃/参数非法/未知工具都返回结构化错误而不拖垮其他来源。
- 替代：searcher 的 SearchService 单一 Tavily 调用与 KE 的裸检索不构成 Agent 可调用工具面——没有来源登记、没有同构 Evidence、没有失败契约；本轮不改它们（P2.5 已删其 fake success），迁移接入留给 P3d。
- 理由：P3d Agent 循环的输入就是"Question → Evidence[] → Reader input"，先把这条链路的存储与契约立住（同构 Evidence、稳定 citation_id、去重与发现 provenance），Agent 才能只决定"调哪个工具"而不必关心来源差异；全文/摘要边界（content_scope）现在就强制，避免 P4 评测时出现"摘要冒充全文"的假阳性。
- 验收：`evidence/tests` + `tools/tests` + `tests_bridge/test_p3c_source_identity.py` 共 46 例全绿——KB/Web/论文各自身份字段齐全、所有来源同构 Evidence 且 validate 通过、citation_id 前缀正确且内容敏感、伪造 citation_id 与同 id 异内容被拒、不同论文版本不合并、跨渠道同论文合并保留双发现 provenance、arXiv 节流生效、source_fetch 拒绝未登记 source/私网重定向/超限内容、evidence_read 拒绝未登记与错页、执行器拒绝未知工具名/未知参数且隔离工具崩溃、SSRF 目标（localhost/私网 IP/file://userinfo）全拒。全部 fake/recorded，无凭证不联网。CI 的 providers 作业扩为跑 providers+evidence+tools+tests_bridge。

## 2026-10-10 P3d：有界 Agent Loop、Reader RRF 与 Citation Gate v1（垂直切片闭环）

- 决定：新增顶层 `agent/` 包完成"Question → Agent → Tool → Evidence → Reader → Citation Gate → Answer/Refusal"闭环。`budget.py` 立硬边界（max_round=3、max_tool_calls=12 含 retry/fetch/read、max_tokens=20000、deadline=180s，clock 可注入；超时优先于超量报告）；`reader.py` 固定 RRF（k=60、w(kb)=1.0/外部=0.7、池 KB20/外部10、输出 top8、同 channel 去重不计重复赞成票、RRF 与原始分另存）；`citation_gate.py` 落地四步验证（citation 存在 → scope 覆盖 → 数字/引号专名字面存在（全角/半角归一化，回应 2026-09-18"全角数字假拒答"发现）→ 语义复检可注入）；`loop.py` 状态机 PLAN→TOOL_CALL→EVIDENCE_UPDATE→GAP_CHECK→GENERATE→VERIFY→DONE，停止原因精确到 sufficient_evidence/budget_exhausted/deadline_exceeded/no_progress/citation_gate_failed，循环检测键=规范化工具+参数（重复且无新 Evidence 即停），引用闸门失败只允许一次重生成且预算跨轮累计不重置。
- 边界：本轮**不做** SSE/HTTP/Redis——trace 事件类型已按 SSE 事件名对齐（meta/plan/tool_call/tool_result/evidence/citation/done/error），SSE v1 与 `/api/v1` 落地随 P3d 后续小步做；LLM 经 providers.LLMProvider 协议注入（本轮测试全部 fake LLM 驱动真实 loop/executor/store，不 stub topology）。
- 取舍：writer 输出非法 JSON 时视为该轮验证失败（走重生成/拒答），不让异常裸抛穿透 Agent；answer 与 refusal 严格分开（AgentAnswer.status），拒答附 refusal_reason。
- 理由：这是第一个完整 Demo 的地基——Agent 只决定下一动作，工具白名单/预算/RRF/引用验证全部确定性执行（design.md §5）；先闭环后接线，避免在没有可测核心的情况下堆 SSE/UI。
- 验收：`agent/tests` 24 例全绿——预算默认值与四种超限、RRF 共识优先/重复调用不双计/池截断/k60 公式、闸门拒未登记引用/scope 不足/数字专名缺失/语义失败与全角命中、垂直切片走通（调工具→证据→充分停止→生成→闸门通过→answered）、重复无进展早停、工具预算封顶、deadline 停止、无证据拒答、闸门两次失败拒答、重生成可挽救、白名单拒绝任意工具名。全量 95 例（providers 25+evidence/tools/bridge 46+agent 24）。

## 2026-10-10 P3d 后半：SSE v1 事件层 + Agentic 任务桥 + /api/v1 公共接口

- 决定：三件套落地"第一个可演示 Demo"。**SSE v1 事件层**（`app/services/sse_v1.py`）：事件信封 `v/task_id/event_id/sequence/type/occurred_at/payload`，类型对齐 design.md §8（meta/plan/tool_call/tool_result/source_status/evidence/token_delta/citation/done/error）；`done` 与 `error{fatal:true}` 是终态（至多一个、必须最后），`error{fatal:false}` 为过程诊断（引用闸门失败/重复无进展），两类语义由 payload 区分。回放按执行计划用 Redis Stream（XADD 显式 ID=`<sequence>-0`，Last-Event-ID 即回放位置），**只负责 event replay、不做 Agent crash recovery**；直播分发走进程内队列（沿用多实例边界裁决的单实例部署）。订阅竞态用"先注册直播队列、再读持久化回放、按 sequence 去重"解决——完成后再订阅、断线重连均不丢不重。
- **Agentic 任务桥**（`app/services/agentic_service.py`）：新建 AgenticTaskService 而非改 ResearchService——复用同一 TaskStateStore/状态语义/取消删除/孤儿标记（"接到任务生命周期"），旧报告拓扑零改动（迁移期纪律）。Agent trace 经 sink 翻译为 SSE 事件（tool_result 派生 source_status）；终态由服务统一发（done 带回答结局 / error{fatal} 带失败），保证终态唯一。生产运行时全云端：缺 DEEPSEEK_API_KEY 时任务显式 failed（error code=config_missing），不降级本地/模拟模型（AGENTS.md）；web/arXiv/kb 单源缺配置或故障按工具级 error 隔离，不拖垮任务。
- **/api/v1**（`app/api/routes_v1.py` + `problem.py` + `schemas/agentic.py`）：`POST/GET/DELETE /api/v1/tasks`、`POST …/cancel`、`GET …/events`（SSE，支持 Last-Event-ID 头与 query 两种续传位点）；FastAPI schema 为 OpenAPI 契约来源；错误统一脱敏 `application/problem+json`（type/title/status/detail/instance/request_id + 稳定 code）。**兼容期按路径分支**：非 /api/v1 路径的错误形状逐字保持旧样（HTTPException `{detail}`、校验 `{detail:[...]}`、BaseAppError/未捕获 `{code,message,details}`），旧接口回归与 OpenAPI 检查都有断言护住。
- 替代：(1) 不把 SSE 事件直接塞进旧 `/research/{id}/stream` 的无信封事件流——旧流无 sequence/回放/终态契约，改动会破坏旧前端回归；v1 并行新增，旧接口兼容期保留。(2) 回答结局不与任务状态混成一个枚举：拒答是 completed 任务的 `answer.status=refused`（附 refusal_reason），`error` 只描述任务失败——"任务结果与拒答分开"（design.md §8）落实为两个正交维度。
- 竞态修复（测试暴露的真问题）：(a) 终态必须**先落持久化/终态事件、后落内存记录**——否则观察者见 status=completed 时事件流还可能缺终态，删除/订阅会踩到收尾中的任务；(b) 取消可能落在 `_run` 首个 await 之前（协程从未启动、不会自补终态），cancel_task 改 async：cancel 后等句柄落下，若仍无终态由取消方补唯一终态事件，订阅方不会挂死；重复取消幂等（cancel_requested 标记），不二次打断收尾。
- 顺带修正（design §8 明文要求、原实现缺口）：Citation Gate 语义复检（SemanticVerifier）的调用计入共享 Budget 并可发 token_delta（stage=verify）——"验证/重生成使用剩余任务预算"此前只覆盖了重生成；token_delta 现覆盖 plan/generate/verify 三阶段，P4 成本统计口径由此成立。工具结果/引用与 call_id 的关联在 trace 与 SSE 上补齐（tool_result、evidence 均带 call_id）。
- 取舍/已知边界：token_delta 是**调用级用量**（generate 非流式，P3a stream 贯通前不做逐 token 流）；Redis Stream 事件 TTL 3 天、进程内直播（单实例）；Redis 故障时事件降级为仅直播并告警、不伪造回放（与 task_state_store 容错一致）；真实云 smoke（真 DeepSeek 驱动端到端）未跑，全部测试 fake/recorded。
- 验收：新契约 100 例（+5 agent 事件 sink）+ researcher 113 例（原 74 + SSE 语义 20（内存与 fake-Redis 双后端同套）+ agentic 桥 10 + /api/v1 契约 9）+ KE 98 回归全绿。P3d 的"SSE 工具/证据/引用/终态顺序、完成订阅竞态、终态重连及回放、任务结果与拒答分开、旧接口兼容回归与 OpenAPI 检查"均有断言；取消生效与 call_id 关联在桥/HTTP 层复验。

## 2026-10-11 P4 第一轮 baseline：冻结件 + 可复现 runner + 指标机械实现

- 决定：按 roadmap P4 前置"跑分前冻结"落地 `eval/baseline/round1.freeze.json` + `round1.md`——18 题（KB/多步/web/paper/版本对照/应拒/近似干扰全覆盖）、数据集 sha256 指纹、模型/索引/提示词/Reader/闸门版本、预算（3/12/20000/180s）、每条件 3 次、评分机械口径与**预冻结门槛**（安全样例与预算合规 1.0 硬门槛；引用准确率 ≥0.8、拒答准确率 ≥0.75、误拒率 ≤0.25、答案机械分 ≥0.6；非回归容差 C ≥ A − 0.05，按 roadmap 取消"全指标超单源"）。runner 起跑前校验指纹，不一致拒绝跑分；门槛失败禁止事后放宽（分析→记 decisions→重跑）。
- 对照公平性：A（KB-only）/B（固定混合）/C（agentic）**共用同一 AgentLoop 的 GENERATE→VERIFY 段**——A/B 预置固定检索进 EvidenceStore、planner 恒停；C 由 planner 有界循环取证。生成器、Reader RRF、引用闸门、预算完全一致，对照只反映检索方式差异。检索指标在融合 top-8 截断前的 RRF 全序上算（roadmap P4 明文）。
- 检索基线：本地确定性 bigram FTS（`eval/corpus_search.py`，含《标题》/条文号加成）——**不用 embedding**（embedding 是云能力，接入须换索引身份重冻结重跑）；design.md 明文允许本地 FTS/RRF。页文本来自语料 pages.jsonl，扫描件无文本层即如实缺席，不伪造。
- 机械评分口径（freeze scoring_rules 的实现）：gold 命中 = 语料 (doc_id,page) / 论文 (arxiv_id+版本，版本不匹配不算) / URL（同 host 且尾段互含——"canonical_url 命中"在跑分前定死的机械解释，非事后放宽）；无 gold locator 的题（topic_absent 应拒题）recall/MRR 记 **n/a 不记 0**；答案正确率 = required_points 归一化逐字覆盖、forbidden 命中即 0，只作可复现代理，最终裁决人工（LLM 辅助不得单独裁决）；OCR/视觉指标 P3b 前记 n/a 不填 0。
- fake 模式定位：脚本 LLM + MockTransport 录制响应走**真实**检索/工具/Reader/闸门代码，只验证 runner 机械正确性；报告标 `mode=fake` + `not_a_conclusion=true`，禁止引用为评测结论。live 模式缺 DEEPSEEK_API_KEY（全条件）或 TAVILY_API_KEY（B/C，外部源是条件定义的一部分）即显式失败退出（AGENTS.md），不降级。
- 安全样例五种（runner 每次运行必跑，硬门槛 1.0）：无登记引用、伪造 citation_id、越权工具名、超预算续调（预算封顶计费）、摘要冒充全文（claim scope=fulltext 但证据 abstract）——全部必须拒答。
- 测试暴露并修复两个真问题：(1) `run_condition` 自建 EvidenceStore 而工具登记进另一个 store——循环查不到任何证据（C 全拒答才暴露）；改为调用方持有 store、工具与循环共享（与生产同构，AgentLoop 本就不自行登记工具证据）。(2) **空 claims 被闸门当通过**——loop 文档"拒答条件含引用不足"但实现漏了：writer 输出空 claims 视为该轮验证失败（走一次重生成），仍空则拒答；不让无据文本冒充成功答案（agent 测试已补）。(3) 顺带修正：无 gold 题的检索指标从"记 0"改"记 n/a"，避免分母虚压 recall。
- 验收：新契约 115 例全绿（P4 机械验收 14 例：指标纯函数/gold 命中规则/确定性检索/三条件 fake 端到端/空 claims 拒答/安全样例全拒/冻结指纹防篡改/live 配置门）；KE 98、researcher 113 回归确认；runner fake 自检三条件跑通（recall@10=0.7059、MRR≈0.64、安全 5/5）——此为机械信号非结论。**live 正式跑分待用户配置云凭证**（DEEPSEEK_API_KEY/TAVILY_API_KEY），届时按冻结门槛出 A/B/C 对照报告并保留均值/波动/95% CI 与 cost_unknown 标记。

## 2026-10-11 P5 第一版：统一前端三栏（Conversation / Evidence / Task Timeline）

- 决定：`frontend/` 落地统一研究前端（Vue 3 + Pinia + Vite + TS，轻依赖、手写设计系统，不搬旧 Element Plus/vue-flow/html2pdf——那些是报告流水线资产）。三栏按 execution-plan Phase 5：Conversation（提问/回答+逐条 claims+引用芯片/拒答/失败/取消可观察）、Evidence（来源与内容范围徽章、文档页码/URL、原文摘录、点击引用芯片高亮）、Task Timeline（SSE v1 事件实时流 meta→plan→tool_call→tool_result→source_status→evidence→token_delta→citation→done/error + 停止原因/预算/用量摘要；不含模型隐私推理——事件契约本就不带 prompt）。
- 行为约定：多会话不串流（切换任务即断旧流、按 sequence 去重）；断线重连走浏览器 EventSource 自动 `Last-Event-ID` 续传并给出可见提示；回答结局（answered/refused）与任务生命周期（completed/failed/cancelled）在渲染层也分开（拒答=黄色正常结局卡，失败才进错误卡）。
- 替代：不复用旧 Vue 工程整体——旧前端是 8 角色报告 UI（已降级为可选拓扑），契约是旧 `/api/research`；新 UI 直连 `/api/v1` + SSE v1，重建比改造便宜且旧前端在替代验收前还不能删。旧两套前端暂留 CI 矩阵，替代验收后删除。
- 联调证据：浏览器实测通过（创建任务→时间线实时→回答+引用→芯片高亮 gold 证据卡含"第 3 页/不少于六个月"原文）；联调用 `scripts/ui_smoke_server.py`（**FAKE 运行时**，脚本头显式标注非生产入口、产出非结论；生产入口仍是 uvicorn main:app，缺云配置显式失败）。
- 顺带修复（联调暴露）：SSE 时间线出现重复 meta——服务的权威 meta（含预算）与 loop trace 的 meta（仅问题文本）都进流；`_forward` 现在跳过 loop 侧 meta/done（终态本来就是服务统一发），终态唯一契约不受影响。
- CI：frontend-build 矩阵加入 `frontend/`（vue-tsc 严格类型检查在 CI 内联跑）。P5 云配置面板（provider/model/base_url/key 加密存储、出站逐能力授权 UI）随后落地，密钥不进 localStorage/GET/日志的约束从第一版就成立（当前界面无任何密钥入口）。

## 2026-10-11 P5 云配置面：凭证加密存储 + 云出站逐能力授权

- 决定：`SecretVault`（Fernet，主密钥来自启动环境 `CONFIG_ENCRYPTION_KEY`）+ `CloudConfigService`（env 启动参数 vs 运行时覆盖）+ `OutboundGate`（逐能力指纹授权）+ `/api/v1/config*` 与前端设置面板。五能力（llm/embedding/reranker/ocr/vision）配置字段沿用 `.env.example` 契约（`{CAP}_PROVIDER/_MODEL/_MODEL_VERSION/_API_KEY/_BASE_URL`）；运行时覆盖存 `data/cloud_config_overrides.json`（非密文字段）+ `data/cloud_secrets.json`（仅密文）。
- 安全约束落实（design.md §9 逐条）：主密钥缺失/格式不符/强度不足（32 字节中不同字节 <16）拒绝保存凭证与启用该能力，不回退明文或临时密钥；GET/日志/trace 永不回显密钥（视图只回 configured/missing，前端输入框只写不读且不落 localStorage）；校验失败保留旧值（先验后写）；删除覆盖即恢复环境值；主密钥轮换先全量重加密并验证可解再原子替换，失败保留旧密文；provider/endpoint/model 变更使旧出站授权失效（指纹不含密钥）；凭证不等于授权——配置验证 live 探测也需 `confirm_fingerprint` 显式确认本次外送。
- 出站门：`CLOUD_DATA_UPLOAD_ALLOWED=false` 总开关默认拒绝一切外送数据的调用，逐能力授权映射存 `CLOUD_DATA_APPROVALS_JSON`（env）+ 运行时覆盖（UI 授权按钮）；留存提示在 UI 可见。**边界**：出站门目前是配置面/验证面的授权闸；把 `check_outbound` 接进每个 provider/工具出站调用点（LLM/搜索/fetch/OCR/vision）随 P3a 剩余与 P3b 的 provider 接入一并落，届时"默认拒绝"才覆盖运行时调用——roadmap 已标注。
- embedding 变更打 `index_migration_pending` 标记（P3a 的 EmbeddingIdentity/CollectionBinding 契约）：UI 可见"待索引迁移"；索引迁移执行器随 KE 接入，未迁移前不得当作新索引已生效（不在本模块偷偷换 collection）。
- 取舍：新模块命名 `cloud_config_service.py` 避让旧 `config_service.py`（SQLite 模型槽，旧路径零改动）；`cryptography==44.0.0` 进 environment.yml 与本机 multiagent（装依赖已在动手前说明：必要性=凭证加密硬要求，体积约 3–4 MB wheel，无更轻的正当替代）。端点校验复用 P2.5 的 `endpoint_guard.validate_model_endpoint`（官方主机 allowlist、https-only）。
- 验收：researcher 125 例（+12 配置面）、新契约 115、前端构建 43 模块全绿；浏览器实测设置面板（默认拒绝/指纹表/主密钥缺失警告）符合验收描述。user 侧截图验收与真实云验证（填真实密钥打真实 provider）待用户操作。

## 2026-10-11 P3b：多模态入库（云 OCR/vision + 逐页回退流水线 + 溯源到 citation）

- 决定：`providers/ocr`（协议 OCRBlock/OCRPageResult：转录+阅读顺序+bbox 0–1+可选置信度；fake 可编排成功/低质/失败 + **真实百度 OCR 适配器**——token 换取/缓存、location 像素归一化、错误六分类、缺配置显式失败）与 `providers/vision`（协议 VisionObservation 按 text_in_image/observation/inference **分开标注**；fake + **真实 OpenAI 兼容 VLM 适配器**——GLM-4V/Qwen-VL 等，https-only、强制结构化输出、解析不出结构即 INVALID_RESPONSE 不冒充转录）。`ingest/pipeline.py` 逐页 **native → OCR → vision** 回退，产出多模态 Evidence（page/rotation/bbox/asset_id/asset_hash 全程保留，extract method/provider/model/confidence 真实记录，推断只进 derived_observations 不回填 raw_text）。
- 发布门（design.md §7）：必需页最终 failed → `publishable=False` 且失败页+各阶段原因显式报告；非必需页失败也报告但不阻发布；低置信度页标 low_quality 并如实记 confidence（不得被忽略）；文本层页不再 OCR（文本层与 OCR 不重复）。
- 图注-资产关联：页内图像资产登记为 `asset` 型 Evidence（locator.asset_id/asset_hash/bbox + 图注文本同证据携带），"child 不切断图注与资产联系"落实为同一 Evidence 上的绑定；原生页与 OCR 页都保留该关联。
- 范围取舍（诚实声明）：Celery 心跳/租约 fencing、真实 KE 上传→worker→index→检索 integration（roadmap P3b 后半）**本轮不做**——需要 Docker/PG/Redis/Qdrant 基建与 P1/P2 真实入库迁移，属于"硬化轮/KE 接入"序列；OCR/vision 实际质量按 roadmap 归 P4 分层裁决。vendor 选择：首个真实 OCR 选百度（协议简单、bbox 可用），首个 vision 选 OpenAI 兼容 VLM（用户可自选 base_url，无绑定）；后续加供应商只加 adapter 不动核心。
- 验收：新契约 128 例全绿（+13）；P3b 验收要点中"fixture 覆盖原生/扫描/混合/旋转/含图、页码/bbox/hash 到 citation 不丢、文本层与 OCR 不重复、fake 响应/低质量/失败可测、失败页不发布完整版本"均有断言。KE 98、researcher 125 回归确认。

## 2026-10-11 硬化轮：JWT 认证、API 限流、观测与 Compose 最终形态

- 决定：**认证**——`app/core/auth.py` JWT HS256（pyjwt==2.10.1，装前已说明；不手写 JWT 避免算法混淆风险）。`AUTH_ENABLED=true` 时 /api/v1 全部受保护（`/auth/token`、`/metrics` 公开），未认证 401、配置缺失/弱密钥（<32 字符）503 auth_not_configured——显式失败不静默放行、不用临时密钥；bootstrap 账号（AUTH_BOOTSTRAP_USER/PASSWORD）以常数时间比较校验，token 短 TTL 只含 sub/iat/exp。默认 `AUTH_ENABLED=false` 仅限本机开发（配套收紧 HOST 默认 0.0.0.0→127.0.0.1，design.md §9"默认仅本机访问；开放到网络前必须认证"）；前端登录层 token 只驻内存不落 localStorage。旧 `/api/*` 兼容期不加认证（旧前端无登录态，且默认仅本机监听），随旧前端一并退场。
- **限流**——`app/core/rate_limit.py` 进程内固定窗口（query=20/min 提问、ingest=10/min 配置写、default=120/min），429 problem+json + Retry-After；单实例内存实现与多实例边界裁决一致（分布式限流是明确非目标），进程重启清零可接受。
- **观测**——`LOG_FORMAT=json` 切 loguru serialize（结构化日志行）；`GET /api/v1/metrics` Prometheus 文本（http_requests_total/auth_failures_total/rate_limited_total/task_terminal_total，纯内存计数，不含任何用户内容/密钥）。
- **Compose 最终形态**——root docker-compose 六服务（postgres/redis/qdrant/backend/worker/frontend）+ 三个 Dockerfile（researcher 后端含顶层契约包、KE worker（镜像含历史 torch 依赖——全云迁移完成后按 roadmap 瘦身）、frontend 多阶段 nginx 反代 /api 且关闭缓冲以支持 SSE）。`docker compose config` 静态校验通过；**本机无 Docker 守护进程，全栈起栈冒烟未执行**（唯一待用户项）。README 换 execution-plan 的 Portfolio 描述 + 三失败案例演示说明（无证据拒答/来源冲突/provider failure，前两者有自动化断言，后者由 P2.5/P3a 契约覆盖）。
- 验收：researcher 132（+7 硬化）、新契约 128、KE 98、前端构建全绿；"未认证请求被拒且限流生效、日志/指标可查、README 换描述、失败案例可演示"均有实现与断言，"Compose 全栈可起并通过冒烟"待用户环境执行。

## 2026-10-11 硬化轮补丁：出站门从配置面接到出站构建点（闭合自标缺口）

- 决定：此前出站门只护住配置/验证面（decisions 同日已标注缺口），本轮接线到**所有生产出站构建点**：`build_cloud_runtime`（researcher 生产路径）与 `eval/runner` live 模式在构造 LLM/搜索工具前逐能力 `check_outbound`（llm/search:web/search:arxiv），未授权显式 `cloud_upload_not_authorized` 并**回显所需指纹**（拒绝即指导）。凭证不等于授权从此覆盖运行时：默认 `CLOUD_DATA_UPLOAD_ALLOWED=false` 下任何 live 任务/跑分都拒绝外送。
- 一致性修正：runtime 的 LLM 配置改为从配置面解析（`LLM_PROVIDER/LLM_MODEL/LLM_API_KEY/LLM_BASE_URL` + 加密覆盖），`DEEPSEEK_API_KEY/DEEPSEEK_MODEL` 保留为兼容回退（P4 冻结契约与 README 提及的环境名不破坏）；搜索来源（Tavily/arXiv 外送**查询**——design §9 明文计入外送）纳入出站视图与 UI 指纹表（search:web/search:arxiv），逐能力授权/失效语义与模型能力一致。
- 可测性/运维：`CLOUD_CONFIG_OVERRIDES_PATH`/`CLOUD_SECRETS_PATH` 环境覆盖存储位置（默认 data/ 不变）。
- 验收：researcher 134（+2）、六目录 128（P4 live 门测试扩出站维度）全绿；默认拒绝、逐能力独立、指纹变更失效均有断言。

## 2026-10-12 根 .env 生成与凭证复用（零代码改动）

- 决定：由 `.env.example` 生成根 `.env`（gitignored、chmod 600，Compose backend/worker 均以 env_file 读取）。DeepSeek 与 Tavily 凭证**复用** `researcher/deep_research_system/.env` 既有 key（同机、同项目、同一用途的模型池配置；四把 MODEL_* key 实测为同一把），不在对话/文档中出现明文；`DEEPSEEK_API_KEY`/`DEEPSEEK_MODEL` 同步填入（eval runner 与 runtime 兼容回退的冻结契约名）。
- `CONFIG_ENCRYPTION_KEY` 由 openssl 随机生成（Fernet urlsafe-base64 32 字节、不同字节 30 ≥ 16），写入前经 SecretVault 真实代码往返验证（加解密、密文落盘无明文、删除、弱钥拒绝）；仅经启动环境提供，不进仓库。
- 保留不动：`CLOUD_DATA_UPLOAD_ALLOWED=false` 与 `CLOUD_DATA_APPROVALS_JSON={}`——出站授权是用户核对供应商条款后的逐能力决定，凭证≠授权，不因配置生成而代开；`EMBEDDING_*`/`RERANKER_*` 留空（无云适配器，禁本地降级为 mock/本地权重）；OCR/VISION 凭证槽位留空待用户申请。
- 契约缺口备忘（待批准后修 `.env.example`）：OCR 段只列 `OCR_API_KEY`，但 BaiduOCRProvider 需 API Key + Secret Key 两个凭证，`.env` 已加 `OCR_API_SECRET` 槽位。另一处 P3b 接线注意：`endpoint_guard.ALLOWED_PROVIDER_HOSTS` 中百度条目名为 `ernie`，OCR 适配器 `provider_name` 为 `baidu`，出站门接入 OCR 时需统一命名或扩注册表。
- 验收：researcher 134、六目录 128、`check_repo_contracts.py` 全绿（本轮零代码变更）；SecretVault 实测通过；`docker compose config -q` 用真实 .env 静态校验通过。
- 补充（同日）：用户提供百度 OCR（API Key+Secret Key）与阿里云百炼 qwen3-vl-plus vision 凭证，已填入 `.env` 对应槽位（不回显、不入仓）。vision 端点取 `…/compatible-mode/v1`（openai_vlm 适配器拼 `base_url/chat/completions`，`/api/v1` 是 DashScope 原生协议变体不适配）。**待裁决**：该端点是租户主机 `llm-pbhfa5rmunurn3vb.cn-beijing.maas.aliyuncs.com` 而非官方 `dashscope.aliyuncs.com`，`endpoint_guard.ALLOWED_PROVIDER_HOSTS`（精确匹配）会拒绝——扩白名单属安全相关代码改动，未经用户批准不改；真实 smoke 调用属用户数据外送，待出站指纹授权后执行。

## 2026-10-12 出站授权开启、租户主机白名单核准与真实 smoke

- 决定（用户同日三项批准）：① **出站授权全开五能力**——用户核对条款后按确认文案填 `CLOUD_DATA_REGION`/`CLOUD_RETENTION_POLICY_NOTE`（region 进指纹，改动即授权失效），`CLOUD_DATA_UPLOAD_ALLOWED=true`，指纹经生产路径 `approve_outbound` 逐能力登记并镜像写 `.env` 的 `CLOUD_DATA_APPROVALS_JSON`（runner 只读 env 的 `OutboundGate.from_env`，两处必须一致）；② **白名单精确增补** `ALLOWED_PROVIDER_HOSTS["qwen"] += llm-pbhfa5rmunurn3vb.cn-beijing.maas.aliyuncs.com`（用户租户主机，不做后缀通配；兄弟租户/端口借用/串 provider 三种攻击面写成拒绝测试，+4 例）；③ vision 端点定 `…/compatible-mode/v1`。
- 实测踩坑（记为契约知识）：`.env` 中 `CLOUD_DATA_APPROVALS_JSON` 这类含双引号的值必须**整体单引号包裹**——bash `source` 会把内层双引号按引号语法剥离得非法 JSON，`OutboundGate.from_env` 对坏 JSON 静默回落 `{}`，症状是 `capability_not_approved`。首轮八项门检踩中，改引号后全放行。
- `.gitignore` 增 `**/data/cloud_secrets.json`、`**/data/cloud_config_overrides.json`：P5 凭证密文与运行时覆盖属既有"本地凭证与运行时配置"忽略段的延伸，防误提交。
- 真实 smoke（合成 PNG"HELLO 2026"+合成查询，无用户数据）：vision qwen3-vl-plus OK（7 条 observations，text_in_image/observation/inference 分层符合 P3b 契约；合成 5×7 像素字体被读成 2025，是测试图保真度问题非链路问题）；LLM deepseek OK；Tavily OK。**OCR 待用户侧**：token 换取成功证明 key/secret 有效，general 接口回 `No permission to access data` = 百度控制台未开通"通用文字识别"产品，开通后复测。
- 验收：researcher 138（+4）、六目录 128、契约与 Compose 校验通过；出站门八项（runner 3 + 配置面 5）全新进程实测放行；P4 live 跑分（18 题×3 条件×3 次=162 次 agent 运行）已按冻结件在后台起跑。

## 2026-10-12 P4 live 首跑暴露 LLM 消息协议违约（修复）

- 现象：live 首跑 162 次运行全量秒挂 `AttributeError: 'dict' object has no attribute 'role'`，报告自标 `not_a_conclusion`（诚实标注）；fake 模式 129 例测试全绿却拦不住。
- 根因：`agent/loop.py` 三处 `generate` 调用传裸 dict，违约 `LLMProvider` 协议 `Sequence[LLMMessage]`；fake LLM 容忍任意消息形状，接缝违约只有真实适配器（DeepSeek，读 `.role`）会暴露。
- 决定：**修调用方而非放宽适配器**——loop 三处改构造 `LLMMessage`，`eval/runner.FakeEvalLLM` 的 dict 下标访问同步收紧为 `.content` 属性（fake 与真实适配器同宽严，防止同类违约再次从 fake 溜走）；新增回归测试断言 generate 收到的全部是 LLMMessage。不采纳"适配器兼容 dict"方案：协议类型就是契约，宽容化会让违约永久化。
- OCR 产品定位（用户出示百度控制台调试截图）：用户 key 的 scope 仅 `brain_ocr_general_basic`——`general_basic`（通用文字识别-标准版）200 可用，`general`（标准含位置版，适配器为取 bbox/置信度所用）回 error_code 6。**待用户在控制台追加鉴权"通用文字识别（标准含位置版）"**；备选是适配器降级用 `general_basic`（丢 bbox/置信度，P3b 证据契约降级，不推荐）。
- 验收：六目录 129（+1 回归）、researcher 138、契约通过；live 接线冒烟（条件 A ×1）真实指标产出证明修复有效；完整 P4 live 重跑后台执行中。

## 2026-10-12 P4 live 首轮正式跑分：硬门槛全过，两道质量门槛未达（不放宽，记录待改进）

- 结果（18 题×3 条件×3 次=162 次运行，0 error，wall 821s，报告 `round1.live.20261012-132444.json`）：**安全样例 5/5 拒答 ✓、预算合规 ✓（硬门槛全过）**；引用准确率 0.9535/1.0/0.9776 ✓（≥0.8）、拒答准确率 0.75/0.75/0.9167 ✓（≥0.75）、非回归 C 0.381 ≥ A 0.3095 − 0.05 ✓；**误拒率 0.4286/0.4762/0.381 ✗（≤0.25）**、**答案机械分 0.3095/0.2976/0.381 ✗（≥0.6）**。按冻结件纪律门槛失败**禁止事后放宽**，记分析待改进轮重跑。
- 归因（细节数据支撑）：① 全部 83 次拒答 100% 是 `citation_gate_failed`（无一例 no_evidence/budget），即 writer 产出的 claims 过不了引用闸门、一次重生成仍失败 → 整题拒；② 检索 recall@10=0.7059 是答案质量天花板（约 29% 金点从未被检回，retriever=local-bigram-v1）——证据不全时 writer 倾向越权表述 claims，被闸门正确拦截，但结果是**整题拒绝而非部分作答**，直接打在 v1"部分有据则部分回答"需求上；③ 三条件 refusal 拒因分布完全一致（A/B 无工具、C 均 3.2 次工具调用），说明瓶颈在生成-闸门环节而非工具编排。
- 改进方向（均属新改动，待批准后实施）：writer 提示词落实"部分有据则部分回答"；闸门/loop 对 claims 逐条取舍（dropped unsupported claims 后以有据部分作答，而非整题拒）；检索侧提升召回（云 embedding/reranker 迁移，属 P1/P2 集成尾巴）。
- 数据可信度备注：`verified_gold=0`——题目金点未逐字核验（eval 语料轮已知 verified 全 false），答案机械分按未核验金点计算，只作方向参考；检索指标与 fake 轮完全一致（本地检索确定性），符合预期。

## 2026-10-12 生成模型切换：DeepSeek → opencode.ai mimo-v2.6-pro（用户指令）

- 决定：用户指令"调用这个服务而不是 deepseek"，生成/规划/验证 LLM 切到 `https://opencode.ai/zen/go/v1` 的 `mimo-v2.6-pro`（OpenAI 兼容 chat/completions，1M 上下文、推理模型带 `reasoning_content`）。凭证存 `local-llm-service.md`（**gitignored**，含 key，禁止提交）与 `.env`；`DEEPSEEK_*` 保留为兼容回退与基线复现（去 `LLM_*` 即回 deepseek）。
- 接线改动（最小必要）：① `eval/runner._live_llm` 从只读 `DEEPSEEK_*` 改为 `LLM_*` 配置面优先、`DEEPSEEK_*` 回退并**传 base_url**（纯 .env 无法切——旧代码不传 base_url 会把新 key 打到 api.deepseek.com；方向沿用硬化轮"LLM_* 为配置来源"决议）；`require_live_config` 同步接受 `LLM_API_KEY`，出站指纹 preset 的 provider 标签改读 `LLM_PROVIDER`（与配置面指纹一致）；测试补 LLM_* hermetic 清理。② `DeepSeekLLMProvider` 增可选 `extra_headers`（不承载凭证）：opencode 网关要求 `x-opencode-session` 稳定会话 ID（官方文档：路由/缓存优化用，客户端自生成），runtime/runner 以 `LLM_SESSION_ID`（可选）或进程内 uuid 注入；契约测试 +1。
- 实测坑：mimo 是**推理模型**——smoke 首发给 `max_tokens=8` 全被 `reasoning_content` 消耗，`content=None` 触发 INVALID_RESPONSE；放开上限后正常。loop/runner 不传 max_tokens，无此风险；教训是冒烟压测要给推理模型留出推理预算。
- 出站授权：LLM 身份（provider/endpoint/model）变更使旧指纹失效，已按生产路径重登记五能力（地域备注同步更新为"opencode.ai：未核对"，用户可补核对结论）；用户切换指令即本次外送确认。**白名单缺口**：`endpoint_guard` 不含 `opencode.ai` 主机——运行时/runner 不校验可用，P5 设置面板保存会拒；是否扩白名单待用户批准（同租户主机先例）。P4 冻结件记录的模型身份是 `DEEPSEEK_MODEL/deepseek-chat`，mimo 跑分属**对比实验**不覆盖冻结基线。
- 验收：六目录 130（+1 extra_headers 契约）、researcher 138、契约通过；出站门八项全新进程放行；`_live_llm` 真实路径 smoke OK（4.4s，'OK'）；P4 对比跑（mimo）后台执行中。

## 2026-10-12 收尾三件：OCR 含位置版复测通过、opencode 入白名单、.env.example 补 OCR_API_SECRET

- OCR 复测（用户开通"通用文字识别（标准含位置版）"后）：`general` 端点 OK 0.4s，合成图转录 `'HELLO'`、bbox 归一化 0–1、confidence=None 如实记录（响应未给 probability，不伪造）——**四路 smoke（OCR/视觉/LLM/搜索）至此全通**。
- 决定（用户同日批准 2、3 两项）：① `endpoint_guard.ALLOWED_PROVIDER_HOSTS` 增 `opencode: ("opencode.ai",)`（精确主机匹配；+3 测试：网关放行 1、错主机/串 provider 拒绝 2）——设置面板现在可保存 mimo 配置，白名单缺口闭合；② `.env.example` OCR 段补 `OCR_API_SECRET` 字段（契约缺口闭合：百度需 API Key+Secret Key 两件）。
- 验收：researcher 141（+3）、六目录 130、仓库契约全绿。`.env.example` 的 `LLM_SESSION_ID` 小缺口同日经用户批准补齐（opencode 会话头可选覆盖值，缺省自动生成 uuid；补后仓库契约校验通过）。

## 2026-10-21 Deep Research 上游调研：保留证据契约，优先显式缺口循环

- 决定：本轮仅做用户要求的三项目源码调研，新增 [deep-research-comparison.md](deep-research-comparison.md)，不修改生产代码、模型配置、依赖、路线图阶段或冻结评测件。QX 确认为 qx-labs/agents-deep-research；三仓库均锁定核查提交、许可证与归档状态。
- 保留：Evidence v2、Source Registry、ToolExecutor、Citation Gate、共享预算和 SSE v1。理由：上游的自然语言研究摘要、模型自报完成、分支轮次/并发限制不能替代本项目的溯源、失败语义及全任务预算契约；生产继续全云、无本地权重或 mock 降级。
- 候选顺序（尚未实施）：QX 显式知识缺口及验证反馈闭环优先；Skywork 仅借鉴结构化委派与完成条件；Open Deep Research 作为同源同模型同预算的 Supervisor 对照参考。理由：现有 AgentLoop 已可追加检索，旧图已有分层结构，近期更应解决缺口可追踪性与 P4 已记录误拒/质量门槛问题，不能凭增加 Agent 数量宣称增益。
- 范围边界：Skywork 当前主分支重心已转向自演进资源体系，不迁入；Open 已归档，仅锁版本参考。部分作答必须重建并核验正文；分层并行需在阶段前置及范围确认后实验。以上均为调研建议，不代表实施批准或阶段验收通过。

## 2026-10-21 dev 分支 Deep Research 改进计划

- 用户要求在 dev 分支修改项目、先制定计划；已核实当前分支为 dev，保留上一轮未提交调研与决策记录。本轮新增 [实施计划](deep-research-improvement-plan.md)，业务代码尚未修改。
- 顺序：先核对阶段前置和回归基线，再修停止判定、增加显式知识缺口、接通验证反馈与受限部分作答，最后同预算消融和 P4 重新验收。理由：先消除错误完成信号并解决已有误拒问题，便于逐步归因，不以多 Agent 数量替代质量证据。
- 保留共享预算、证据登记、引用闸门、云出站授权和全云约束；不改历史评测件及阶段状态。Supervisor/结构化委派为验收后的下一轮候选，不并入本轮核心实施。

## 2026-10-21 Windows 离线评测：固定冻结输入的换行

- 现象：本机无常用路径凭证文件，LLM_API_KEY/DEEPSEEK_API_KEY/TAVILY_API_KEY 环境变量未配置；离线评测启动被冻结指纹拦截，P4 测试 13 passed / 1 failed。
- 根因：两个冻结 JSONL 在 Git index 中为 LF、本机 checkout 为 CRLF；原始字节 hash 不匹配，而换行恢复 LF 后及 HEAD 字节 hash 均与冻结件一致，证明此次差异只在换行。
- 决定：新增 .gitattributes 仅将题库和 manifest 固定 eol=lf，并恢复本地对应换行。保留逐字节指纹检查，不重算冻结值、不改题目、不放宽门槛。理由：跨系统 checkout 应复现同一冻结数据；缺云凭证不通过本地模型或 mock 质量分替代正式评测。此次 fake 运行仅验证评测机制和安全样例。

## 2026-10-21 dev 实施切片 1：规划校验与停止原因

- 用户授权按既有计划实施。新增 [机制说明](agent-mechanisms.md)，逐项说明加入原因、行为、保留约束和测试证据；不宣称 P4 质量门槛已通过。
- 校验 planner 输出，不再将畸形结果默认为空调用；预算前后检查、轮次耗尽及无进展保留真实停止原因，writer 成功不覆盖。理由：修复假完成信号，为后续缺口闭环提供可靠控制状态。
- 基线六目录 130 passed。新增 7 个控制流用例先验证全部失败，修改后 agent+P4 为 52 passed；原 no_progress 测试的 sufficient_evidence 断言按本次语义修正。原公开枚举不变。
- 本机研究服务缺 loguru/aiosqlite；在 gitignored .venv（复用既有依赖）补装清单已声明的 loguru==0.7.3/aiosqlite==0.22.1，不修改应用依赖清单，不安装本地模型。研究服务回归另记实测结果。


## 2026-10-21 dev 实施切片 2：显式缺口与证据反馈

- 新增 GapLedger，复用 Citation Gate 验证闭合；条件不可改写、缺口不可删除消失、总数最多 12；planner 输入增加来源身份/范围、尝试与错误、预算，plan/tool_result 承载关联，结果增加向后兼容 gaps。
- 原因：缺少可验证的研究覆盖状态和错误反馈会导致盲目搜索/假闭合。保留旧 tool_calls-only 格式供历史对照与兼容，不声称该格式具备缺口覆盖证明。
- source_fetch 从 EvidenceStore 已登记来源衔接 SourceRegistry，避免选对工具却永远 source_not_registered；逐跳获取防护保持。arXiv 摘要 URL 不冒充全文；真实 PDF 文本提取仍需独立已授权链路，不在此假装实现。
- 对应 agent/tools/bridge 84 passed，研究服务桥 10 passed；本轮无真实云请求。每项机制的目的与边界见 agent-mechanisms.md。


## 2026-10-21 dev 实施切片 3：验证反馈、部分作答和共享预算

- 结构化失败原因驱动受限补检索，复用原检索循环与去重状态；最多一次重生成，不新开免费预算。理由：泛化重写提示不能解决正文/证据缺失。
- 最终正文只从通过闸门的 claims 重建；第二次仍有失败项时保留安全部分并返回 limitations，无通过项仍拒答。理由：过滤 claims 但保留自由 answer 会泄漏无据结论，整题拒绝又浪费已有支持。design.md 同步本次用户授权的部分作答语义。
- Budget.guard/模型计账覆盖规划、生成、缺口闭合和验证；用剩余时限取消在途调用、给剩余输出上限，实际超限仍计账并拒答；父取消不吞。保留云协议和出站授权，不宣称能撤销单次已计费超量。
- 结果 schema/服务/前端增加兼容字段 gaps/limitations，前端仅补必要局限与缺口进度，不重设计 UI。服务测试脚本补第三次显式 PLAN_DONE，适配新增的有限修复规划，保留“无支持仍拒答”原断言。
- 六目录 151 passed；服务 API 13 passed（含部分作答 HTTP/SSE）；服务桥 10 passed；前端 npm ci（锁文件未变）后 build 全绿。真实云质量仍未验证。


## 2026-10-21 Agent 阅读上下文与消融隔离

- 实际读取结果补最多 4000 字上下文，优先放入 writer 的 8 条证据窗口；只有登记证据可进入，原 RRF 指标排序不变。理由：此前 evidence_read 的结果被 200 字摘要及旧 top8 再次截掉，无法实现计划中的定向补读。
- verification_feedback=False 同时关闭失败反馈内容，不仅关闭额外工具调用；理由：gap-only 消融不能偷偷获得反馈提示。模块单独提交，不与评测代码混在一起。
- 真实读工具回归先红后绿，agent/tests 53 passed；公开状态与云配置均未改。


## 2026-10-21 评测执行接口模块

- run_condition 接受可注入 loop_factory，并保存 gaps/limitations/工具轨迹，默认仍运行现有 AgentLoop，A/B/C 含义不变。工具构建器可显式加入 fetch/read，并支持注入受上下文管理的 HTTP client；理由：对照需要共用真实流水线而非复制业务实现。
- 安全 fixture 为额外修复规划提供有效停止输出，不能因脚本耗尽的格式错误而假通过；增加断言确保伪引用/摘要越权确因引用闸门拒绝。P4 14 passed，旧 A/B/C fake runner 完整跑通，safety=PASS。该模块独立提交。


## 2026-10-21 评测资产模块：RFC 字节复现

- 完整语料检查发现三个 RFC txt 的 Windows checkout CRLF 与冻结 LF 不符；已逐一验证 HEAD 和恢复 LF 的 hash 都等于原 manifest 值。仅给这三个路径增加 eol=lf 并恢复本地换行，不改语料或冻结值。理由：正式跑分前必须验证原资产，不能只校验题库/manifest 自身。
- check_corpus.py 与 P4 14 项测试全部通过，按用户要求作为独立模块提交。


## 2026-10-21 前后对照评测模块

- 新增 compare_agents.py 与独立冻结件，旧 loop 固定为本轮初始提交 8486709e8e41ffd80aca2442ef60d71aabefa2b5 并核验源码 hash；共用当前依赖/五工具，明确不是完整旧系统复现。理由：避免维护三套复制实现，又能真实运行原控制流程。
- baseline/gaps/feedback 同题同模型同预算，逐题配对，按相同请求共享外部首响应并保存证据快照；三组分别跑安全套件。记录源码指纹、实际模型身份、用量、错误/拒因、缺口/重复调用/部分作答指标，金额未知明确标注。
- 机械自检：新增测试 5 passed；18×3×3 共 162 次 fake 运行零 error、各组三个条件均通过五安全样例；report agent-improvement.fake.20261021-230512.json 自标 not_a_conclusion=true。无凭证 live 入口启动前显式拒绝，不改出站授权。
- 此为 P4 对照基础设施交付，不代表模型质量过门槛；真实云对照与人工金标准核验待外部条件就绪。按模块独立提交，后续 Supervisor 仍不实施。
