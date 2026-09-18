# 迁移与演进路线图及阶段验收

更新：2026-09-18。根 `AGENTS.md` 的阶段验收以本文件为准。**未达本阶段验收，不进入下一阶段；文档已修改不代表功能已完成。**

## 编号与当前状态

`knowledge_engine` 自带 Phase 0–10 是 RAG_sec 的历史编号，与本项目无关。本项目旧 P0–P2 是迁移基线，保留含义；本次新增 P0R 并扩展 P3，不把已迁移源码重新编号成已完成的云模型/Agentic 功能。

| 阶段 | 目标 | 当前证据与状态 |
| --- | --- | --- |
| P0（历史） | 原规格、固定目录与原样搬运 | 2026-09-17 骨架已完成，搬运 hash 结论见历史决策；原规格已由新设计替代 |
| 基线轮 | 可回归测试、配置模板、Git 基线与 CI | 本机测试与提交已记录；GitHub PR CI 全绿尚未验证，不宣称验收完成 |
| P1（历史） | 平移 RAG_sec | 搬运及 96 个非 integration 测试通过；34 个 integration 测试尚未验证 |
| P2（历史） | 平移 MultiAgentIR | 搬运及 47 个原测试通过，不证明真实 graph/工具/云协议已通过 |
| P0R | 重冻结 Agentic、扩源、多模态与全云模型规格 | 本轮更新文档；供应商/协议选择尚未完成，不实现业务代码 |
| P3a | 云模型 Adapter 与配置/索引身份 | 未开始 |
| P3b | PDF、云 OCR/vision 与可溯源入库 | 未开始 |
| P3c | KB/Tavily/arXiv 工具与来源 Registry | 未开始 |
| P3d | Agentic RAG、Reader、引用闸门、公共接口/SSE | 未开始 |
| P4 | 质量、消融、云费用与可靠性评测 | 未开始 |
| P5 | 统一研究前端与云服务配置 | 未开始 |

## P0（历史）— 规格与骨架

- **目标**：固定六目录，复制两套源码与测试，基础设施 Compose 和原版设计/决策成文。
- **前置**：保留原仓库，不重新生成源码。
- **验收**：目录与规格完整，搬入文件 hash 对比无差异。历史验收不用于证明新需求。
- **状态**：骨架历史已完成；现在以 [design.md](design.md) 为目标规格，历史保留在 [decisions.md](decisions.md)。

## 基线轮 — 工程守护

- **目标**：复现两套既有测试，模板/README 自洽，版本控制与 CI 可用于后续 diff/回归。
- **前置**：无业务代码改动；不能为 CI 全绿顺手重构旧代码。
- **验收**：两套测试命令/数量/环境记录在 [testing.md](testing.md)，根模板存在，基线提交可审计，CI 在 main push 上全绿。
- **状态**：本机记录为 KB 96 passed/34 deselected、researcher 47 passed；基线提交已完成；**CI 已于 2026-09-18 在 main push 上实测全绿（6/6，run #2）**。旧本地 torch 测试环境只作迁移回归，AST 导入声明核对不是干净安装或云协议通过的证明——但 CI 里的 knowledge_engine 作业走的是干净 `pip install -e ".[test]"`，该项已由 CI 覆盖。

## P1（历史）— 平移知识引擎

- **目标**：保留旧私库源码与测试，迁移时只改包名/路径，功能零改动。
- **前置**：原测试一起搬入，不剥离 Celery worker/beat。
- **验收**：原非 integration 测试全绿；真实测试数据库及 PG/Redis/Qdrant integration 另行通过，不对含用户数据的数据库运行清表测试。
- **状态**：非 integration 基线已记录，integration 未完成；新需求不受历史“永远不改能力”约束，但变更只能发生在后续明确阶段。

## P2（历史）— 平移编排层

- **目标**：保留旧研究编排源码与测试，搜索测试使用 mock。
- **前置**：迁移不附带新功能。
- **验收**：47 个原测试全绿；mock 不作为生产成功来源。
- **状态**：原测试基线已通过，统一工具调用仍待实现。

## P0R — 目标规格重冻结

- **目标**：直接以 Agentic RAG、KB/Tavily/arXiv 工具、云 OCR/vision PDF 入库为目标，不另交付一版仅固定流水线的产品。固定 RRF 只作对照及降级算法。
- **前置**：需求变更获得用户同意；保留旧测试/迁移记录；基线 CI 与旧 integration 缺口分别显式跟踪。
- **内容**：版本化 Evidence/ToolCall/Source Adapter，页/区域/资产语义，云 LLM/embedding/reranker/OCR/vision 配置与失败矩阵，预算与终止策略，云出站授权，索引重建/回滚；供应商稍后由用户选择，不预设所有供应商兼容 OpenAI。
- **验收**：设计、路线图、决策、README、根模板无互相矛盾的生产目标；移除本地模型路径要求；每类启用能力确认具体 provider/model/协议/维度/版本/限额与数据留存条款；预算与数据授权可测试；待接入值保持空而不是伪默认。文档一致性通过不等于供应商接入完成。

## P3a — 云模型与配置契约

- **目标**：所有模型推理走云端 Adapter；本机继续存储、文件解析及确定性检索。按配置、协议、可靠性、索引身份四个小切片执行，不大改两套应用。
- **前置**：基线轮及 P0R 验收；用户确定需要的首批云供应商。云 reranker 可显式关闭，关闭只使用 RRF，不切回本地模型。
- **内容**：独立 LLM/EMBEDDING/RERANKER/OCR/VISION 配置与凭证绑定，缺配置/401/429/5xx/超时/取消/畸形响应处理，batch index 映射、输入/输出用量；文本流、tool call、vision content；embedding 模型/维度/预处理身份、replace/reindex 贯通与新 collection 切换。
- **验收**：fake HTTP/stream 协议契约测试及错误矩阵全绿；乱序/缺项/重复 batch、维度不符/非有限向量能被拒绝；超时/重试不超 deadline；索引/查询身份一致，模型切换可重建及回滚；生产路径不加载权重或导入本地推理库，无本地模型/mock fallback；干净安装的目标运行环境无 torch/transformers/sentence-transformers/OCR 权重需求。旧本地模型相关测试可迁为对应云契约断言并记录理由，不用删除测试掩盖回归。真实云 smoke 单独授权，不由普通 PR 触发。出站 false/空授权时所有模型、rerank、搜索查询与远程 fetch 不发请求，内部 FTS 可用；能力/provider/endpoint/model fingerprint 不匹配拒绝上传，新配置要求重新授权。模型 endpoint 只受信 HTTPS、密钥绑定主机且不跨重定向发送；针对误配/恶意 endpoint 与验证请求均有无泄漏契约测试。

## P3b — PDF 切分与云 OCR/图像识别

- **目标**：文本、扫描、混合、含图 PDF 与独立图片均能入库，证据可回指真实页/区域/资产。
- **前置**：P3a 模型契约与出站授权，P1 真实入库 integration 验收，原资产访问与版本发布机制明确。
- **内容**：文本层/扫描区域识别、云 OCR 阅读顺序/bbox、云 vision 观察与推断分离，论文/图注关联切分、parent-child 与 page/block 坐标，原文件/hash/处理版本；云调用心跳、租约 fencing、缓存/幂等、索引清理、失败页显式报告。
- **验收**：固定 fixture 覆盖原生/扫描/混合/多栏/旋转/跨页/含图 PDF 与图片；页码/bbox/hash 从 parser 到 citation 不丢；child 页范围真实，图注与图片关系保留；文本层与 OCR 不重复；云模型 fake 响应/低质量/失败可测；所需页失败不发布“完整”版本；上传→worker→cloud fake→index→检索的 integration 通过；租约失效 worker 不能发布或污染新版本。OCR/vision 实际质量在 P4 分层裁决。

## P3c — 工具与搜索源 Registry

- **目标**：KB 检索、Tavily Web 搜索与 arXiv 学术搜索都成为 Agent 可调用工具，新增 provider 不修改核心 Agent。
- **前置**：P3a 的查询/云配置契约与 P3b Evidence 溯源稳定。
- **内容**：`kb_search`、`web_search`、`arxiv_search`、`source_fetch`、`evidence_read`，schema 白名单、provider 能力/健康/限额、结构化错误、来源身份/去重；arXiv ID/版本/DOI、摘要与正文范围；受控获取全文/PDF与 SSRF 防护。
- **验收**：`tests_bridge` 验证 KB 带 doc/version/chunk/index、Web 带 URL/fetched_at、论文带 arXiv ID/版本；所有来源输出同构 Evidence；Tavily/arXiv 均有 fake provider 行为测试，不仅定义插件入口；单源故障不影响健康源，生产不返回 example.com mock；跨源同论文合并保留发现 provenance，不同版本不误并；全文失败不以摘要支撑全文断言；节流/取消/大小限制/逐跳 SSRF 与工具结果注入样例通过。

## P3d — Agentic RAG、引用闸门及公共接口

- **目标**：Agent 由问题和证据决定调用/追加检索与停止，KB 作为确定性工具，不再嵌套无界 Agent；每次回答有可验证证据。
- **前置**：P3a–P3c 验收，旧任务生命周期与 SSE 回归保持，云 LLM 明确支持受校验工具调用。
- **内容**：规划/拆问/查询重写/源路由/有界循环，Reader RRF 与可选云 rerank，调用轨迹/预算/循环检测/取消，文本与视觉引用验证、一次重生成后拒答，统一 `/api/v1` 和 problem+json，版本化 SSE 及 Last-Event-ID 回放。
- **验收**：fake LLM 驱动实际 graph/executor（不能仅 stub topology）验证首次选工具、证据缺口触发追加检索、充分证据后停止；未知工具/非法参数/重复无进展/超预算/超 deadline 被阻止，retry/fetch/read 计费计数且取消生效；所有工具结果与引用能关联 call_id；无登记/无据/错误 OCR 数字/未验证图像结论触发拒答；引用闸门不会保留不受支持句子，重生成不重置预算；已有充分证据可在限额内作答。SSE 工具/证据/引用/终态顺序、完成订阅竞态、终态重连及回放通过，任务结果与拒答分开。旧接口兼容回归与 OpenAPI 检查通过。

## P4 — 评测与消融

- **目标**：量化 Agentic RAG、arXiv、OCR/vision 的实际增益、费用及失败行为，而非只证明 HTTP 200。
- **前置**：P3d 验收；跑分前冻结数据集、人工标注规则、模型/索引/提取/prompt 版本、预算、质量非回归容差与分层质量/延迟/费用门槛，写入 `eval/`。阈值未冻结则不进入正式评测。
- **内容**：旧 golden set 加外网必答、论文摘要/全文、多步、无据拒答、扫描/混合/图像样本；A KB-only、B external-only、C 固定混合、D 同源同模型同预算的 Agentic 各 3 次，补去 arXiv/去 OCR-vision/禁追加检索/去云 rerank 消融。
- **验收**：可复现 runner 输出 指标为 Recall@5/10/20（截 top-8 前）、MRR、引用准确率、拒答准确率、答案正确率、误拒率、工具/终止合规、来源覆盖、OCR CER/WER、视觉正确率、页/区域引用准确率、p95 延迟、token/API 费用与 provider 失败/重试；结果含均值/波动/置信区间和成本未知标记。遵守预冻结门槛，无登记证据/越权/伪证据/超预算安全样例全部拒绝。取消“融合所有指标同时超过每个单源”要求，失败则分析并记录决策后重跑，不能事后放宽阈值让其通过。

## P5 — 统一前端及云服务配置

- **目标**：研究对话、证据引用、会话任务三栏；用户可自行设置云模型和来源，无需编辑源码。
- **前置**：P3d HTTP/SSE/Evidence/ToolCall 契约冻结、P4 验收；配置接口有认证、权限、加密及出站授权。
- **内容**：复用旧 Vue 的 SSE/Pinia 可用逻辑但适配新契约；展示计划摘要、工具状态与终止原因，不展示隐私推理；PDF 页跳转、OCR bbox/图片区域定位，区分原文/摘要/视觉推断。UI 设置云 provider/model/base_url/key、来源与受控参数，启动基础设施/加密主密钥仍走环境；支持验证及恢复环境值。
- **验收**：截图验收及接口联调通过；引用跳转真实原页/区域/图片，论文版本和内容范围明确，多会话不串流、取消/重连/拒答可观察；密钥不进 localStorage/GET/日志，配置验证失败保留旧值，主密钥缺失/弱/格式不符拒绝凭证保存，轮换失败不丢旧密文；云出站逐能力授权与留存提示可见，provider/endpoint/model 变更不能沿用旧授权；embedding 切换触发索引迁移。旧前端仅在替代功能验收后删除，同时更新其 CI 构建任务。

## CI/CD 与测试分层

- 现有 CI（PR 与 main push）含五个作业：knowledge_engine 测试、researcher 测试、两套前端构建、gitleaks 密钥扫描、**仓库契约**（`eval/corpus/check_corpus.py` + `eval/questions/validate_questions.py` + `scripts/check_repo_contracts.py`）。它们只保证迁移回归与仓库契约，不宣称已覆盖 Agentic、多模态或云协议，也不新增 ruff/mypy/格式门禁。
- 仓库契约作业守护的是**证据本身**（语料 sha256、页数、题集逐字可溯源、不可再分发内容必须被忽略、配置模板不含真实密钥、阶段验收齐全、决策只追加）。它不检查代码风格，所以不构成对旧代码的新门禁。
- P3 按能力加无凭证 fake/recorded cloud、工具、索引身份、OCR/vision fixture 和真实 graph 契约测试；mock 明确限于测试，记录响应脱敏且不包含用户私密资产。
- 真实 PG/Redis/Qdrant integration 使用专用测试库，可先放 main/手动/定时任务；真实云 smoke 与质量评测另用授权凭证、样本和预算，普通 PR 不调用付费云服务。
- 公共契约冻结后检查 OpenAPI/SSE 兼容；签名、多架构镜像、固定 Compose/.env.example、升级/索引迁移说明及发行包在应用可发布且端到端 smoke 通过后由 tag 触发。CD 是用户可安装发行物，不连接用户本机自动部署。
