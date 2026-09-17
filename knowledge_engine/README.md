# CyberSec RAG Agent — 网络安全领域 RAG 知识库系统

> 当前实现进度：**Phase 10：评测体系与 `/api/v1/eval/run`**
> 权威实现规格见 [`Doc/文档2.MD`](Doc/文档2.MD)。
> Claude Code 仓库操作说明见根目录 [`CLAUDE.md`](CLAUDE.md)。

本仓库是一个面向**网络安全法规、标准、教材与知识资料**的 RAG 知识库后端项目。
当前已经完成：

- **Phase 0**：工程骨架、FastAPI、Docker Compose、PostgreSQL / Redis / Qdrant 联通
- **Phase 1**：ORM 模型、Alembic 迁移、初始数据库 schema、最小 CRUD、数据库测试基础
- **Phase 2**：上传入口、本地原始文件存储、`file_hash`、`document` / `document_version` / `ingest_task` 创建
- **Phase 3**：PDF / Markdown / TXT 解析、基础清洗、失败状态回写
- **Phase 4**：parent-child chunk、`chunk_hash`、结构化切分、chunk 落库
- **Phase 5**：embedding / reranker 包装、Qdrant upsert、PostgreSQL FTS、自动建索引
- **Phase 6**：混合检索、metadata filter、RRF、`/api/v1/query/retrieve`
- **Phase 7**：safety_guard、intent、term expansion、rewrite、`/api/v1/query/rewrite`
- **Phase 8**：parent context 回取、answer_generator、citation_checker、`/api/v1/query/answer`、query_log
- **Phase 9**：`replace` 接口、`file_hash` 快速比对、`chunk_hash diff`、unchanged child 向量复用、soft delete、Qdrant/FTS 可见性关闭接口
- **Phase 10（当前）**：`eval/golden_dataset.jsonl`、`eval_service`、`/api/v1/eval/run`、Recall@K、MRR、citation accuracy、refusal accuracy、`eval_runs` / `eval_run_items` 持久化

当前仍**没有实现**：自动知识更新、复杂反馈闭环。

## 文档导航

- [项目启动与使用指南](Doc/项目启动与使用指南.md)
- [项目架构文档](Doc/项目架构文档.md)
- [项目技术栈文档](Doc/项目技术栈文档.md)
- [全链路验证与修复报告（2026-07-17）](Doc/全链路验证与修复报告-2026-07-17.md)
- [功能性问题审计修复与测试报告（2026-07-03）](Doc/功能性问题审计修复与测试报告-2026-07-03.md)
- [项目技术面试说明（HTML）](Doc/项目技术面试说明.html)
- [前端工程 README](frontend/README.md)
- [前端阶段面试学习版](Doc/前端阶段面试学习版.html)
- [Phase 10 面试学习版](Doc/Phase10面试学习版.html)

---

## 1. 当前阶段一句话说明

> 当前项目已经不仅能上传、索引、检索、回答和做增量更新，还开始支持基于 golden dataset 的量化评测：可以运行 `/api/v1/eval/run`，并把 Recall@K、MRR、citation accuracy、refusal accuracy 与 item 级结果持久化到数据库。

---

## 2. Phase 10 新增的核心能力

### 2.1 golden dataset 文件化

- 新增 `eval/golden_dataset.jsonl`
- 每一行定义一个评测样本：query、期望 doc_type、期望 chunk、是否应拒答等
- 让评测输入可复用、可回放，而不是靠人工临时提问

### 2.2 eval run 持久化

- 新增 `eval_service.run_eval(...)`
- 自动写入 `eval_datasets`、`eval_dataset_items`、`eval_runs`、`eval_run_items`
- 支持保存 run 级指标与 item 级结果，便于后续对比系统迭代前后效果

### 2.3 指标计算

- `Recall@K`：是否把目标 chunk 检索出来
- `MRR`：目标 chunk 首次出现的位置质量
- `citation accuracy`：答案引用是否能被证据校验器接受
- `refusal accuracy`：对该拒答的问题是否真的触发拒答
- `average_latency_ms`：平均处理耗时

### 2.4 评测接口

- `POST /api/v1/eval/run`
- 默认运行 `golden-dataset`
- 返回 run_id、样本数和上述核心指标摘要

---

## 3. 当前明确未实现的内容

- 自动从互联网同步法规
- 复杂版本对比页面
- 复杂反馈闭环
- 可视化评测 dashboard

---

## 4. 当前关键文件

- `eval/golden_dataset.jsonl`：Phase 10 golden dataset
- `backend/app/services/eval_service.py`：评测主逻辑与指标计算
- `backend/app/api/eval.py`：`/api/v1/eval/run` 接口
- `backend/app/schemas/eval.py`：评测接口 schema
- `backend/tests/test_eval_service.py`
- `backend/tests/test_eval_api.py`

---

## 5. Phase 10 的关键设计点

### 5.1 为什么必须做评测持久化，而不是只打印日志？

因为日志只适合一次性观察，不能稳定比较“这次改动后 Recall@K 是上升还是下降”。评测要成为工程能力，就必须沉淀到 `eval_runs` / `eval_run_items`。

### 5.2 为什么 refusal accuracy 要单独统计？

因为这个项目有明确的安全边界。一个安全领域 RAG 不能只看“答得准不准”，还要看“不该答的时候有没有拒答”。

### 5.3 为什么 citation accuracy 不能等价于 answer quality？

因为它衡量的是“引用是否真的被证据支持”，是 groundedness 的最低门槛；答案质量还涉及表达、覆盖度与完整性。

---

## 6. 常用命令

```bash
pytest backend/tests/test_eval_service.py
pytest backend/tests/test_eval_api.py -m integration
```

---

## 7. 当前项目已经覆盖到哪里

到 Phase 10，项目已经覆盖：

- 文档上传与版本化
- 解析、清洗、parent-child chunk
- embedding / 向量索引 / FTS
- 混合检索、query rewrite、证据约束回答
- replace / chunk diff / soft delete
- 基础 eval dataset + eval run + 核心指标统计

所以当前项目的本质，已经从“能做一个安全知识库问答后端”进化到“能对这个问答后端做可重复量化评估”。
