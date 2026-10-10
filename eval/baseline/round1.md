# P4 第一轮 baseline 冻结说明（2026-10-11）

机器可读冻结件：[`round1.freeze.json`](round1.freeze.json)。**跑分前冻结；此后不得换题、放宽阈值或改评分规则让结果变好看**——失败先分析、记 `docs/decisions.md`，再重跑（roadmap P4 前置与验收）。

## 题选（18 题，覆盖 KB / web / paper / 多步 / 不可能）

| 维度 | 题 | 说明 |
| --- | --- | --- |
| single_source（KB） | q001–q003 | 单文档单处作答 |
| multi_hop（多步） | q016–q018 | 跨文档两步定位 |
| external_only（web+paper） | q026、q028（arXiv 论文）、q031（网页） | 语料必然答不了 |
| version_contrast | q034（法条新旧版）、q038（论文 v1↔v2） | 版本不误并 |
| insufficient（不可能） | q039（topic_absent）、q042/q045（missing_key_fact）、q048（requires_prediction） | 应拒答 |
| near_miss | q051–q053 | 相邻条款/相似数字干扰 |

- 金标准字段语义、逐字 `required_points`、`forbidden_points`、人工核验流程见 [`../questions/README.md`](../questions/README.md)。
- **verified=0**：候选题集全部未经人工核验；本轮结果一律携带该标注，人工核验后按 REVIEW_CHECKLIST 流程重跑并保留两版结果。

## 条件（同模型、同预算、同生成/闸门，只变检索）

- **A KB-only**：本地语料检索 top20 → Reader RRF top8 → 生成 + 引用闸门。
- **B fixed mixed**：本地 top10 + 外部(web/arXiv) top10 → RRF 融合 top8 → 生成 + 引用闸门（固定混合，无重规划）。
- **C agentic**：AgentLoop 有界循环按需调 kb_search/web_search/arxiv_search → Reader → 引用闸门。

A/B/C 全部走同一个 AgentLoop 的 GENERATE→VERIFY 段（planner 行为不同），生成器、Reader、引用闸门、预算完全一致，保证对照只反映"检索方式"差异。检索指标在融合 top-8 截断**前**的排序列表上计算（roadmap P4）。

## 版本指纹（变更即失效，须重冻结重跑）

- 数据集：`questions.v1.jsonl` 与 `manifest.jsonl` 的 sha256（写入 freeze.json，runner 起跑前校验）。
- 索引：`eval-corpus-pages-v1`（语料页文本 + 本地 bigram 打分 `local-bigram-v1`，确定性、无 embedding）。
- 模型/提示词：`deepseek-chat`（env `DEEPSEEK_MODEL` 可覆盖）；planner/writer/verify 提示词冻结为 P3d v1（`agent/loop.py` 内文案），Reader 与闸门为 P3d v1 实现。
- 预算：max_rounds=3、max_tool_calls=12、max_tokens=20000、deadline=180s；每条件 3 次。

## 评分规则（机械代理 + 人工裁决，LLM 辅助不得单独裁决）

完整定义在 freeze.json `scoring_rules`。要点：

- **Recall@5/10/20、MRR**：按 gold locator 命中（语料项 = doc_id+page；外部项 = arxiv_id+版本或 URL）。
- **引用准确率** = 有引用指向 gold 证据的 claims 比例；**引用覆盖率** = 带引用 claims 比例。
- **拒答准确率 / 误拒率**：按 `expected_behavior` 分母分开算，不混入答案正确率。
- **答案正确率（机械）** = `required_points` 归一化后逐字覆盖率；出现 `forbidden_points` 该题记 0。最终正确率以人工金标准裁决，机械分只是可复现代理。
- **工具/终止合规、来源覆盖、p95 延迟、token/API 费用**（缺用量标 `cost_unknown`，不得按 0 计）。
- OCR CER/WER、视觉正确率、页/区域引用准确率：P3b 前记 **n/a**（不填 0）。

## 预冻结门槛（不达标不算评测通过；禁止事后放宽）

| 门槛 | 值 | 性质 |
| --- | --- | --- |
| 安全样例（无登记引用/伪证据/越权工具/超预算）拒答率 | 1.0 | 硬门槛 |
| 预算/终止合规 | 1.0 | 硬门槛 |
| 引用准确率（机械，answered 题） | ≥ 0.80 | 质量门槛 |
| 拒答准确率（insufficient 题） | ≥ 0.75 | 质量门槛 |
| 误拒率（answered 题被拒） | ≤ 0.25 | 质量门槛 |
| 答案正确率（机械） | ≥ 0.60 | 质量门槛 |
| 非回归容差 | C ≥ A − 0.05（答案机械正确率） | 不要求 C 全面超 A/B |
| p95 延迟 | ≤ 180s | 标记项 |
| 费用 | 无门槛，报数并标 cost_unknown | 标记项 |

## 运行

```bash
# 机械自检（fake LLM/固定响应，验证 runner 与指标正确性；不是评测结论）
python3 eval/runner.py --mode fake --out eval/results/

# 正式跑分（需 DEEPSEEK_API_KEY；B/C 另需 TAVILY_API_KEY；缺配置显式失败）
python3 eval/runner.py --mode live --out eval/results/
```

报告含每条件均值/标准差/95% CI 与逐题明细；`mode=fake` 的报告文件名与内容均标记 fake，不得引用为评测结论。
