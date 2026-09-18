# eval/questions/ —— 人工金标准题目集 v1（全部未核验）

`questions.v1.jsonl`：56 道候选题，**全部 `verified: false`**——按纪律，agent 只产出候选，
`verified` 只能由用户人工回原文核对后置 `true`，任何人不得自行置真。

- 语料：`../corpus/`（28 篇，见其 `README.md` 与 `LICENSES.md`）
- 校验：`python3 validate_questions.py`（离线、纯标准库；56/56 通过、配额达标）
- 人工核对清单：`REVIEW_CHECKLIST.md`（逐题、逐条 required_points 的勾选表）

## 题型与配额

| type | 题量 | 判定要点 |
| --- | --- | --- |
| `single_source` | 15 | 单文档单处作答；恰好 1 个语料内 locator |
| `multi_hop` | 10 | ≥2 个不同文档/版本的两步定位（跨法引用、跨论文、跨 RFC） |
| `external_only` | 8 | 语料必然答不了，必须走 Tavily/arXiv；locator 全部 external，且校验其 arxiv_id 不在语料内 |
| `version_contrast` | 5 | 新旧版本对照（网络安全法 2016↔2025↔修改决定 ×4 + 论文 v1↔v2 ×1）；≥2 个不同文档 locator |
| `insufficient` | 12 | 证据不足应拒答：`topic_absent` 3 / `missing_key_fact` 6 / `requires_prediction` 3 |
| `near_miss` | 6 | 相邻条款/相似术语干扰（90↔60 日、5↔7 日、两档罚款、0-RTT 前向保密等） |

## 字段语义（schema）

- `expected_behavior`：`answered` / `partial` / `refused`。当前 v1 中仅 `insufficient` 为 `refused`。
- `expected_locator`：数组，每项二选一：
  - 语料内：`{"doc_id", "page", "clause?"}`——doc_id 必须在 manifest 中、page 必须真实存在；
  - 外部：`{"external": true, "url", "arxiv_id?", "version?", "note?"}`——仅 `external_only` 题使用。
- `required_points`：**原文逐字摘录**（构建时用脚本从定位页文本机械提取，空白折叠处理换行，
  连字符断词/连字（ﬂ）、全角数字、± 符号均按原字符保留）。评分时每条都必须能在定位页文本中
  逐字命中（`validate_questions.py` 仅忽略空白差异，不做同义改写）。
- `forbidden_points`：不得出现在回答中的表述。用于拦截无据数字、主体对调、旧表述残留。
  与 `required_points` 的冲突定义：forbidden（忽略空白）是 required 的**子串**即冲突
  （评分必然误伤）；forbidden 为包含 required 的更长“错误整句”不算冲突。
- `refuse_reason`：仅 `insufficient` 题必填，取值 `topic_absent`（语料完全没有的主题）/
  `missing_key_fact`（主题相关但缺关键数字或时间，含“旧版为扫描件无文本层”类）/
  `requires_prediction`（要求预测或评价）。
- `difficulty`：1–5。`notes`：出题意图与陷阱说明。

## `verified` 流程（人工专属）

1. 打开 `REVIEW_CHECKLIST.md`，按题逐条核对：
   - 定位页（`pdf/<filename>` 第 N 页，或 RFC txt 对应页）里能否找到该 required_points 原文；
   - 题目措辞是否中立、不诱导拒答或答案；
   - `forbidden_points` 是否会误伤正确答案；
   - `external_only` 题需点开 locator 的 url 人工复核（构建时已用 arXiv API / 官网页核对过一次）；
   - `insufficient` 题确认语料确实无法回答、拒答理由成立。
2. 逐题勾选后在 `questions.v1.jsonl` 中把该题 `"verified": false` 改为 `true`；
3. 重跑 `python3 validate_questions.py` 确认无回归；
4. 修改题目措辞/配额时，同步修改脚本顶部的 `QUOTA` 常量。

## 已知边界

- `external_only` 的 `required_points` 无法离线逐字复核（外部网页内容会变），构建时已经
  arXiv API 摘要原文 / rfc-editor / 网信办官网 / flk API / Qdrant 官方文档逐一核对，
  最终以人工复核为准；
- `insufficient` 中 `topic_absent` 类题目（如 GDPR）在联网配置下理论上可由外部搜索回答，
  其“应拒答”预期针对 KB-only/禁追加检索的消融配置——是否调整由用户决定；
- 版本对照题中 2016 版网络安全法为扫描件，全部对照依据来自《修改决定》与 2025 修正版文本。
