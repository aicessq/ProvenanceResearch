# Phase 10 实施计划（评测与日志）

> 本计划基于当前仓库 **Phase 0~9 已完成或将完成** 的前提编写。
> 
> 本阶段目标是：在不越过规格边界的前提下，完成 **golden dataset、Recall@K、MRR、citation accuracy、refusal accuracy、评测结果持久化以及 eval report 输出**。

---

## 一、Phase 10 的目标

根据权威规格，Phase 10 的唯一目标是：

**把系统从“能运行、能问答”，升级为“能被量化评估、能持续优化”的 RAG 系统。**

这一阶段要解决的问题是：

- 如何准备评测数据集
- 如何执行一批标准化 query
- 如何计算召回与排序指标
- 如何衡量引用准确率与拒答准确率
- 如何持久化评测运行结果
- 如何输出评测报告

---

## 二、必须严格遵守的范围边界

### 2.1 本阶段必须完成

按照规格，Phase 10 必须完成：

1. 实现 `golden_dataset.jsonl`
2. 实现 `Recall@K`
3. 实现 `MRR`
4. 实现 `citation accuracy`
5. 实现 `refusal accuracy`
6. 保存评测结果
7. 输出 eval report

### 2.2 本阶段不要越界实现

本阶段不要提前扩展：

- 不要实现复杂在线学习系统
- 不要实现自动调参平台
- 不要实现前端评测看板
- 不要做过度复杂的可视化系统

### 2.3 Phase 10 的重点是“量化闭环”

这意味着：

- 指标必须可重复计算
- 评测输入必须固定
- 评测输出必须可持久化
- 结果必须能帮助后续优化前面各阶段

---

## 三、当前仓库现状与 Phase 10 的前置条件

### 3.1 当前已具备的基础

进入 Phase 10 前，理论上应已具备：

- Phase 6：可用检索链路
- Phase 7：用户输入优化链路
- Phase 8：可用问答链路
- `eval_datasets / eval_dataset_items / eval_runs / eval_run_items` 表已存在
- `query_logs` 已具备真实记录能力

### 3.2 Phase 10 的关键依赖

本阶段依赖：

- `/query/retrieve` 或底层 retriever 可用
- `/query/answer` 或底层问答链路可用
- `safety_guard` 可稳定拒答高风险请求
- citation 输出结构已固定

如果 Phase 8 还不稳定，就很难做出有价值的评测。

---

## 四、Phase 10 的实施原则

### 4.1 先做小而稳定的评测集，再扩大量

第一版不追求大而全，而应追求：

- 样例少但代表性强
- 每条样例标注明确
- 可反复执行
- 易于定位问题

### 4.2 评测要覆盖“检索、答案、拒答”三类能力

不能只测检索，也不能只测答案。
至少要覆盖：

- 检索召回质量
- 引用正确性
- 攻击性请求拒答正确率

### 4.3 评测结果必须落库

不要只在终端打印一个 summary。
应把：

- run 级结果
- item 级结果
- 指标汇总

都写入数据库，以便后续比较不同版本表现。

### 4.4 评测服务要与线上链路复用核心能力

不要为了评测另写一套完全不同的检索或问答逻辑。
评测应尽量复用真实链路，这样结果才有意义。

---

## 五、建议的实现拆分

建议把 Phase 10 拆成 6 个步骤执行。

---

## 六、Step 1：准备 golden dataset

### 目标

构建第一版可复现评测集。

### 推荐文件

- `eval/golden_dataset.jsonl`
- `backend/app/services/eval_service.py`

### 每条样例建议包含

- `query`
- `expected_doc_type`
- `expected_keywords`
- `expected_chunk_ids`
- `expected_refusal`
- 可选 metadata

### 设计要求

- 样例覆盖法规 / 标准 / 教材问题
- 样例覆盖安全攻击请求
- 样例覆盖概念解释、修复建议、条款查询等典型场景

---

## 七、Step 2：实现检索指标

### 目标

量化检索阶段效果。

### 推荐文件

- `backend/app/services/eval_service.py`

### 最低要求

1. 实现 `Recall@K`
2. 实现 `MRR`
3. 对每条样例记录是否 hit
4. 记录 reciprocal rank

### 指标说明

- `Recall@K`：预期 chunk 是否出现在前 K 结果中
- `MRR`：第一个正确结果排名的倒数平均值

### 注意点

- K 值应与当前检索 top_k 设计保持一致或明确配置
- 若 `expected_chunk_ids` 为空，需要定义对应 fallback 判断逻辑

---

## 八、Step 3：实现答案与安全指标

### 目标

量化回答与拒答质量。

### 推荐文件

- `backend/app/services/eval_service.py`

### 最低要求

1. 实现 `citation accuracy`
2. 实现 `answer groundedness`（如果当前结构可支持）
3. 实现 `refusal accuracy`

### 建议定义

#### citation accuracy

- 引用 chunk 是否真实存在
- 页码与来源是否匹配 metadata
- 答案关键结论是否与引用一致

#### refusal accuracy

- 对攻击性请求是否正确拒答或重定向
- 对合法问题不能误拒答

### 注意点

- 如果 groundedness 第一版难以完全自动化，可先做简化版本，但必须在文档中写清规则

---

## 九、Step 4：实现评测运行与结果持久化

### 目标

让评测可批量运行、可追踪、可比较。

### 推荐文件

- `backend/app/services/eval_service.py`
- `backend/app/api/eval.py`

### 本阶段最低要求

1. 从 dataset 读取样例
2. 为每次评测创建 `eval_run`
3. 为每条样例创建 `eval_run_item`
4. 执行检索 / 问答 / 安全判定链路
5. 写入单条结果
6. 汇总写入 run 级指标

### 建议持久化字段

- `retrieved_chunk_ids`
- `reranked_chunk_ids`
- `answer`
- `refusal_triggered`
- `recall_hit`
- `reciprocal_rank`
- `citation_passed`
- `groundedness_score`
- `latency_ms`
- `error_message`

---

## 十、Step 5：实现 `/eval/run` 与 eval report 输出

### 目标

提供一个能触发评测并查看结果的最小接口。

### 推荐文件

- `backend/app/api/eval.py`
- `backend/app/schemas/eval.py`

### 最低要求

1. 暴露 `POST /api/v1/eval/run`
2. 支持指定 dataset
3. 返回 run id 与状态
4. 输出整体评测结果摘要

### report 最低应包含

- 总样本数
- Recall@K
- MRR
- citation accuracy
- refusal accuracy
- average latency

---

## 十一、Step 6：测试与验收

### 建议新增测试文件

- `backend/tests/test_eval_service.py`
- `backend/tests/test_eval_api.py`

### 至少要覆盖的测试

#### 1. golden dataset 读取

- JSONL 可正确加载
- 样例结构校验通过

#### 2. 指标计算

- Recall@K 计算正确
- MRR 计算正确
- refusal accuracy 计算正确

#### 3. 结果持久化

- `eval_run` 被创建
- `eval_run_item` 被创建
- 汇总指标被写入 run 表

#### 4. `/eval/run` API

- 能成功触发评测
- 返回结构正确
- 可看到 run 结果

### 验收命令建议

如果使用 conda：

```bash
conda run -n rag_sec_phase1 pytest backend/tests/test_eval_service.py
conda run -n rag_sec_phase1 pytest backend/tests/test_eval_api.py -m integration
```

如果使用 venv：

```bash
.venv\Scripts\python -m pytest backend/tests/test_eval_service.py
.venv\Scripts\python -m pytest backend/tests/test_eval_api.py -m integration
```

### Phase 10 验收标准

必须达到：

- 可以运行 `/eval/run`
- 可以看到每条 query 的召回结果
- 可以看到整体 Recall@K 和 MRR
- 可以看到攻击性请求拒答准确率

---

## 十二、推荐文件改动清单

### 需要新增或完善的文件

- `backend/app/services/eval_service.py`
- `backend/app/api/eval.py`
- `backend/app/schemas/eval.py`
- `eval/golden_dataset.jsonl`
- `backend/tests/test_eval_service.py`
- `backend/tests/test_eval_api.py`

### 可能需要调整的现有文件

- `backend/app/services/retriever.py`
- `backend/app/services/answer_generator.py`
- `backend/app/services/citation_checker.py`
- `backend/app/services/safety_guard.py`
- `backend/app/services/crud_service.py`
- `README.md`

---

## 十三、建议的实现顺序

1. 准备 golden dataset
2. 实现检索指标
3. 实现答案与拒答指标
4. 实现评测运行与结果持久化
5. 暴露 `/eval/run`
6. 编写测试
7. 更新 README
8. 验收

---

## 十四、实现时最容易踩的坑

### 1. 评测集过大但标注质量差

这会让第一版评测没有指导意义。

### 2. 评测逻辑与真实线上链路脱节

会导致“测得很好，线上很差”。

### 3. 只打印指标，不落库

后续无法比较不同版本表现。

### 4. 只测检索，不测拒答

对于安全领域系统，这是不完整的。

---

## 十五、最终结论

Phase 10 的本质是：

**把“可工作的 RAG 系统”，升级为“可量化评估、可持续改进的 RAG 系统”。**

完成本阶段后，你将真正拥有一套可以持续优化的工程闭环，而不仅是一个能跑的 Demo。
