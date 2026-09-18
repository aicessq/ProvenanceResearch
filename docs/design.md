# 目标设计：Agentic RAG、扩源与云端多模态

> 更新：2026-09-18。本文件描述待实现的目标，不代表现有程序已经支持。
> 保留 `knowledge_engine/` 和 `researcher/` 的独立进程与迁移测试，不重新生成两套业务代码。执行顺序及验收见 [roadmap.md](roadmap.md)，替代历史决策见 [decisions.md](decisions.md)。

## 1. 产品与模块分工

用户下载项目，在本机运行应用、PostgreSQL、Redis、Qdrant 与文件存储，自己配置云供应商及凭证。**所有模型推理均使用云端模型**：生成/规划/验证 LLM、embedding、reranker、OCR、vision；不下载模型权重，不依赖 GPU，不用本地模型作生产降级。

本地允许做 PDF 文本层提取、页面渲染、图像裁剪、清洗、切分、hash、FTS 和 RRF；这些是文件处理与确定性算法，不是本地模型推理。云供应商由用户后续选择，不能假定 OCR、reranker 与 vision 都兼容 OpenAI 协议。

| 模块 | 目标职责 |
| --- | --- |
| `knowledge_engine` | 原文件/资产管理、PDF/图像入库、云 OCR/vision/embedding、索引版本、可被调用的 KB 检索工具 |
| `researcher` | Agentic RAG 的规划与有界工具循环、来源注册、Tavily/arXiv、Reader 融合、生成及引用闸门、统一公共 HTTP/SSE 接口 |
| Cloud Model Adapter | 按能力封装供应商协议、响应校验、限流、deadline、版本和用量记录；调用者不处理供应商原始对象 |
| `frontend` | P5 的统一研究界面、原文/页/区域定位与云服务配置；两套旧前端暂作过渡资产 |

```text
用户问题 -> researcher Agent -> 校验后的工具执行器
                              |- kb_search -> knowledge_engine -> 云 embedding / FTS
                              |- web_search -> Tavily
                              |- arxiv_search -> arXiv 元数据/摘要
                              |- source_fetch -> 已登记来源的正文/PDF
                              |- evidence_read -> 已登记 chunk、页或图像区域
工具结果 -> Evidence 池 -> Reader 确定性融合 / 可选云 rerank
         -> 判断证据缺口 -> 有预算则追加工具调用，否则生成或拒答
         -> 引用闸门 -> 回答或拒答
```

## 2. 统一 Evidence 与可核验引用

所有来源使用同一个、版本化的 Evidence 结构。`source_type` 描述来源，`modality` 描述模态，`extraction.method` 描述处理方式；增加来源不等于增加第二套答案结构。

| 字段 | 约束 |
| --- | --- |
| `schema_version` | 初版 `2`，公共接口不得静默改变字段语义 |
| `source_type` | `kb_chunk` / `web` / `paper` / `asset`；`paper` 首批为 arXiv，`asset` 为独立或文档内图像 |
| `modality` | `text` / `image` / `mixed`，与 provider 分开 |
| `provenance` | `provider`、标题、内容 hash；KB 必须含 doc/version/chunk/index 身份；网络含规范 URL 与 fetched_at；论文含 arxiv_id、明确版本、可用时 DOI 与正文 URL |
| `locator` | 文件证据的 artifact_id、页码、block/region_id 与 bbox；图片的 asset_id、原资产 hash；页码从 1 开始，bbox 使用旋转校正后页面左上角为原点的 0–1 坐标，保留旋转与尺寸以回指原 PDF |
| `extraction` | `native_text` / `ocr` / `vision` / `provider_text`，带 provider/model/version、预处理/prompt 版本、原始响应引用；没有可靠置信度时为 null，不伪造数值 |
| `raw_text` | 保存抽取文本或 OCR 转录，允许纯图片为 null；不得用 Agent 摘要或视觉推断回填。标注 `content_scope=snippet/abstract/fulltext/region`，禁止以摘要冒充全文 |
| `derived_observations` | 可选视觉观察与推断，分别标记并绑定 asset/region；不是已验证原文 |
| `score` | 原始分只在相应召回列表内解释，RRF 与 rerank 分另存；不跨供应商直接比较 |
| `citation_id` | 回答/任务内稳定，前缀 K/W/A/I 分别对应来源；由完整来源身份、版本、位置及内容 hash 生成并检测冲突，不能只对标题或未版本化 URL 做短 hash |

OCR 转录可能识别错误，`raw_text` 字面匹配并不能证明原图上的事实；图像结论的最终依据是可回看的原资产/区域，不是模型自我生成的描述。parent 上下文若支撑额外结论，应登记其自身 Evidence，而非冒用 child 引用。

## 3. 工具与来源扩展契约

工具执行器负责白名单、JSON Schema 参数校验、预算、取消与 deadline；模型不能提供任意函数名或任意访问地址。工具返回 `call_id/status/evidence/meta/error`，`status` 为 `ok/empty/error`；`meta` 包括 provider、调用耗时、索引/模型身份、用量与覆盖范围；错误脱敏且有稳定 code/retryable。单源失败不取消健康来源，不把 provider 异常或 mock 当成成功证据。

| 工具 | 核心输入 | 来源与限制 |
| --- | --- | --- |
| `kb_search` | query、top_k、mode=`vector/keyword`、文档过滤 | 通过内部 HTTP 调用 KB；两路可独立失败，只召回，不在 Adapter 内偷偷跨源融合 |
| `web_search` | query、top_k、time_range、已启用 provider | 首批 Tavily；provider 是注册值，新增 Adapter 不修改 Agent 核心 |
| `arxiv_search` | query、top_k、日期/分类过滤 | 首批 arXiv；记录论文 ID、版本与摘要范围；官方元数据接口无 API key，不编造必须凭证 |
| `source_fetch` | 已登记 source_id、content_scope | 获取正文或对应版本 PDF；检索与阅读各自计入调用预算 |
| `evidence_read` | 已登记 evidence_id、页/region | 回取 parent、原页或图片；需要视觉理解时调用云 vision，不任意读本地路径 |

Source Registry 维护 provider 能力、启用状态、凭证要求、健康状态与限额。Tavily 与 arXiv 都作为首批交付，不仅预留插件接口。arXiv 按官方使用限制执行节流/缓存，初始请求间隔 3 秒；并发上限不能覆盖来源更严格的限额。

论文优先按 arXiv ID + 版本、可用 DOI 去重；私库按 doc/version/chunk；网页按规范化 URL + 抓取内容版本。相同论文被 Tavily 和 arXiv 命中时合并证据而保留两条发现 provenance，不靠改 URL 多次计分；不同版本不可静默合并。摘要范围内结论可引用摘要，全文断言必须成功获取/解析全文，否则标记缺口或拒答。

检索内容、PDF、图片和工具结果均为不可信数据，不得提升成系统指令。获取远程内容时只允许 HTTP(S)，限制大小/MIME/重定向并逐跳防 SSRF；访问内网 KB 是固定内部地址，不能由搜索结果任意指定。

## 4. 直接实现有界 Agentic RAG

目标不是让 Agent 机械执行每条固定检索链。Agent 根据问题与工具结果规划、拆问、选择 KB/Web/论文来源；证据不够时可改写查询、阅读全文或追加检索；满足证据要求后停止。KB 保持确定性工具，不在其中再嵌套第二个无界 Agent。

循环为：计划 -> 校验工具调用 -> 并行/顺序执行 -> 登记 Evidence -> Reader 融合 -> 判定证据缺口 -> 下一轮或终止。云 LLM 必须能经 Adapter 返回受 schema 校验的工具调用；不支持所需能力时报告配置错误，不能把任意生成文本当可执行命令。Planner、Reader、Writer 和文本 Verifier 默认共享同一 `LLM_*` 云配置，不沿用旧四槽位作为公共配置要求。

| 默认限制 | 值与说明 |
| --- | --- |
| `AGENT_MAX_ROUNDS` | 3，追加检索不得重置 |
| `AGENT_MAX_TOOL_CALLS` | 12，包含工具重试、fetch/read 与 Agent 发起的视觉阅读 |
| `AGENT_MAX_MODEL_TOKENS` | 20000，累计模型输入输出；派生云调用的用量也记账，未知用量不得报成 0 |
| `AGENT_DEADLINE_SECONDS` | 180，任务总 deadline，子请求与退避不能越界 |
| `AGENT_MAX_CONCURRENCY` | 4，仍受各 provider 约束 |
| `AGENT_MAX_COST_USD` | 可选硬上限；启用时必须有供应商计价表/预算估算，无法估算则拒绝启动付费任务，而非假装已执行费用约束 |

执行前预留预算并校验上限，单次 max tokens 不超过剩余预算。云响应超出预估时停止后续调用并记录；并发结束仍要结算实际用量。规范化工具+参数形成循环检测键，没有新 Evidence 的重复调用不无限重试。

终止原因至少包括 `sufficient_evidence/budget_exhausted/deadline_exceeded/no_progress/cancelled/providers_unavailable/citation_gate_failed`。达到检索预算时允许用已有充分证据完成回答；证据不足必须拒答。生成/闸门需事先预留预算，预算不能执行最终验证时不得发出未验证结论。

## 5. Reader 融合与云端 rerank

保留确定性基线：KB vector/keyword 各 top-20、每个选定外部来源 top-10，最终 top-8；`RRF(d)=w(source) * Σ 1/(60+rank_i(d))`，KB 权重 1.0、外部来源 0.7，同分按来源优先及稳定身份排序。RRF 在 Reader 排名步骤执行，不直接比较原始分。

Agentic 路径按实际调用集合融合。每个 provider/channel 维护去重后的排名列表，多次查询按确定规则合并，不把同一工具的重复调用算成多张独立赞成票；固定基线与 Agentic 使用相同融合规则。可选 reranker 在 RRF 后调用云端模型，保留候选 ID/index 映射和独立分数；未启用或云 rerank 失败时保持 RRF 排序。**无本地 reranker fallback。**

## 6. 云端模型契约与索引迁移

能力使用独立前缀：`LLM_*`、`EMBEDDING_*`、`RERANKER_*`、`OCR_*`、`VISION_*`。每类显式配置 provider/model/model_version/base_url/api_key/timeout_seconds/max_retries；密钥只能绑定相应 provider，不能跨槽位借用。可共用云供应商，但不隐式继承别的能力的密钥。支持供应商名单以实际 Adapter 为准，不保证填写任意地址就兼容。

模型 endpoint 默认仅允许已登记、受信的 HTTPS 地址；由管理员明确核准的云代理也要绑定到能力配置身份，禁止 Agent/工具结果修改。验证保存前执行 URL/主机与访问策略校验，不跟随将凭证转发到其他 host 的重定向；API key 只发往其绑定 endpoint，不出现在 URL/query。endpoint 变更要求重新验证与出站授权，不能把旧 key 自动试发到任意地址。内网 KB 固定地址与本机非模型存储不属于模型 endpoint 例外。

Embedding 还需 `EMBEDDING_DIMENSION`；索引与查询必须使用同一 provider/实际模型或明确 deployment 版本、维度、归一化和预处理身份，禁止把可漂移别名声称为固定版本。校验返回数量、index/顺序、维度、有限数值与输入 token/批量上限。rerank 按 index 还原输入映射，校验缺项、重复、分数方向和 top-n。

模型或维度变更时创建新 collection/index_version，重嵌入并核验数量、身份和质量后切换，保留回滚入口；新建、replace 复用和 reindex 的每条向量都带 embedding_identity。禁止跨身份复用向量。OCR/vision 版本或切分策略变更需重新解析/切分，不能仅换 embedding。

失败统一区分缺配置、401/403、429、5xx、连接/读取超时、输入超限、畸形响应、部分批失败与取消；仅暂态错误可有限重试，尊重 Retry-After、退避与总 deadline。生产缺配置/失败不下载本地权重、不生成 mock 证据。向量失败允许 keyword/Web/论文继续；生成 LLM 失败报告 provider 错误，不伪造成功回答。

## 7. PDF 切分、云 OCR 与云图像识别

```text
原文件/图片 -> 原资产存储与 hash -> 逐页文本层/版面提取、图片定位
            -> 原生文本块或云 OCR 转录块 -> 清洗、阅读顺序、结构/页区域切分
            -> parent-child chunk -> 云 embedding -> PG/Qdrant/FTS
图片/图表区域 -> 云 vision 观察/推断 -> 派生检索文本 + 原资产/区域引用
```

- PDF 分类为原生文本、扫描、混合页；低质量/无文本区域才走云 OCR，避免文本层与 OCR 重复入库。处理多栏、跨页段落、页眉页脚和旋转，不把整份文档页范围贴到每个 child。
- 保留法规条款/标题 parent-child 策略，并为论文加入标题/段落/图注关联；child 不能切断关键图注与其资产联系。没有可靠结构时按页内块和长度兜底，保留真实 block/page/bbox 映射。
- 云 OCR 返回转录、阅读顺序、block/bbox 与可用置信度；图片识别保存 asset_id、原图 hash、页/bbox、模型/prompt 版本，将图中文字、可观察内容和推断分开。
- OCR/vision 上传 bytes/multipart 或受控短期资产 URL，不把本地路径当云端地址。限制 `DOCUMENT_MAX_PAGES=100`、`DOCUMENT_MAX_UPLOAD_MB=20`、`IMAGE_MAX_PIXELS=20000000` 与 `INGEST_MAX_CONCURRENCY=2`，供应商更严格时取较小值。
- 元数据必须从 parser 经 cleaner/chunker、PG/Qdrant、Evidence 到 Citation 全程保留；原图、原文件、响应/处理版本可回取。模型置信度不是事实正确概率，低质量标记不得被 Agent 忽略。
- 云 OCR/vision 是目标能力；缺配置时拒绝相关入库/阅读，不能让扫描件空文本“成功”。所需页/模态失败则版本不发布，报告失败页与原因；不默认把不完整文档当已完整入库。
- Celery worker/beat 保留；长云调用需持续心跳、租约 fencing、阶段缓存、幂等重试及孤立索引清理，旧 worker 失去租约后不能发布版本。

首期支持图像/图表中的文字与可核验视觉事实，不承诺通用表格结构还原、精密图表数值计算或任意代码结构理解。

## 8. 引用闸门与终态

每条事实性结论必须挂 `[citation_id]`，引用只能来自登记 Evidence。文本/OCR 验证数字、专名和关键断言的对应 span，再做语义复检；OCR 歧义/关键数字须回看原区域。视觉断言需要绑定原资产/区域并由云视觉验证，不能仅用同模型的文字描述自证；评测采用人工抽样裁决。无法验证的精确数字或图片外推必须拒答。

失败携带脱敏的 unsupported_claims 重生成一次，仍失败返回 `status=refused, reason=citation_gate_failed`，不会把部分不支持的句子留在成功答案中。验证/重生成使用剩余任务预算，不允许新开无限检索循环。`answered/refused` 是回答结果，与任务 `completed/failed/cancelled` 生命周期分开。

公共接口统一 `/api/v1`，FastAPI schema 为 HTTP/OpenAPI 契约来源，错误采用脱敏的 `application/problem+json` 与 request_id。旧接口在兼容期保留，KB 内部接口不直接暴露为前端依赖。SSE 版本化事件含 task_id/event_id/sequence/occurred_at/payload，类型为 `meta/plan/tool_call/tool_result/source_status/evidence/token_delta/citation/done/error`，支持 Last-Event-ID 回放、终态唯一和多任务隔离。UI 展示计划摘要与工具事实，不输出模型隐私推理或未校验结论；只有闸门通过的答案 token 才可作为最终回答展示。

## 9. 本地配置、数据出站与隐私

`.env.example` 是待实现根契约，目前旧子项目尚未全部读取。启动参数（数据目录、数据库凭证、监听地址、配置加密主密钥）由环境/Compose 管理；P5 UI 管理云 provider/model/base_url/key 与受控参数。UI 密钥只写入后端加密存储，GET 仅回 configured/source，主密钥来自启动环境，密钥不进 localStorage、日志、trace 或 SSE。启用密钥存储时 `CONFIG_ENCRYPTION_KEY` 缺失、格式错误或强度不足必须拒绝保存/启动该能力，不能回退明文或临时密钥；主密钥轮换需验证重加密与恢复，不在失败后破坏旧密文。运行时覆盖环境值，删除覆盖即恢复环境配置；候选配置验证失败不替换旧配置。embedding 变更须执行索引迁移，不是保存后立刻查询旧向量。

云端 embedding 上传文本与查询，LLM 上传问题和证据，reranker 上传查询/候选证据，OCR/vision 上传 PDF 页或图像；Tavily/arXiv 与远程 fetch 也会外送搜索查询或访问目标。所有包含用户问题、证据或文件的第三方调用均受出站门禁，而不只是模型调用。`CLOUD_DATA_UPLOAD_ALLOWED=false` 为总开关，拒绝这些外部请求并返回 `cloud_upload_not_authorized`；来源默认启用不等于上传许可，内部 KB 的 FTS/已存原文回取可继续，依赖云 embedding 的向量查询不可绕过门禁。

总开关开启仍需能力/provider/endpoint/model 配置绑定的授权：`CLOUD_DATA_APPROVALS_JSON` 默认 `{}`，映射能力 ID（例如 `embedding` 或 `search:arxiv`）到用户审核的配置 fingerprint。fingerprint 由能力、provider、规范 endpoint、model/version 及数据地域/留存声明产生，不含 API key。只有当前身份匹配才允许上传；新供应商、endpoint、model/version 或地域/留存变更使对应授权失效，P5 保存时必须重新确认。用户核对每个 provider 条款后逐项授权，凭证不等于授权；健康检查/配置验证只能按明确的授权范围发送数据，不能先上传再请求同意。

项目不能保证第三方“零留存”，地域/留存说明不能改变供应商政策。只传必要内容，缓存有版本与清理策略；资产 URL 限权且过期。服务默认仅本机访问；开放到网络前必须认证与权限校验，包括配置和原资产访问。

## 10. 评测与验收

固定数据集包含纯 KB、必须外网、论文摘要/全文、扫描/混合/含图 PDF、独立图片、跨源多步题、缺证应拒答及工具结果注入样本。冻结题集、模型/索引/提取版本、prompt、来源、预算及缓存策略，每组 3 次，报告均值、波动/置信区间。

A/B/C 保留为 KB-only / external-only / 混合固定检索对照；每组分别记录 Tavily、arXiv 和全文覆盖。新增 D 为同源同模型同预算上限的 Agentic RAG，以及去 arXiv、去 OCR/vision、禁用追加检索、禁用云 rerank 消融。

核心指标保留 Recall@5/10/20、MRR、引用准确率、拒答准确率、误拒率和答案正确率；引用准确率为抽样事实断言中被对应证据正确支持的比例，拒答准确率为缺证题正确拒答比例，误拒率为应答题被拒比例，答案正确率依冻结的金标准及人工评分规则，LLM 辅助评分不能单独作为裁决。新增工具选择/任务成功率、预算/终止合规、来源覆盖、OCR CER/WER、视觉事实正确率、页/区域引用准确率、p95 延迟、token/API 成本与 provider 失败/重试率。检索指标在融合 top-8 截断前计算，否则无法合理计算 Recall@10/20。

取消旧的“融合组每项指标都必须超过每个单源组”要求。P4 在首次正式跑分前冻结质量非回归容差、分层最低质量、延迟/费用上限和人工标注规则；没有预先冻结门槛不算评测通过。关键安全样例（无登记引用、伪证据、越权工具、重复循环与超预算继续调用）全部应被拒绝，不以质量平均分覆盖安全失败。

## 11. 非目标与执行纪律

不做无界自主循环、多智能体辩论、自动开放未知工具、权限绕过、多租户/多 KB 泛化、任意代码解析和通用表格结构建模。不做本地模型回退；供应商不支持的能力必须明确不可用。

本次需求明确放行 Agentic RAG、Tavily/arXiv 扩源和云端多模态能力，其他新需求与顺手重构仍需同意。旧源码迁移与测试历史保留；按 P0R、P3a–P3d、P4、P5 的可验证出口推进，不先重写前端，也不把文档更新当功能已交付。
