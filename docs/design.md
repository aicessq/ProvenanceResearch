# 设计文档（一页纸）

> 2026-09-17 定稿。合并 knowledge_engine（原 RAG_sec，私库侧）与 researcher（原 MultiAgentIR_LangGraph，编排侧）。
> 迁移期纪律：只搬运与接线，不改行为；设计变化先改本文件，再记入 docs/decisions.md。

## ① 统一证据模型（Evidence）

进入结论链路的检索结果只有一种结构，不允许第二种：

| 字段 | 约束 |
| --- | --- |
| `source_type` | 枚举：`kb_chunk`（私库切片）/ `web`（网络结果） |
| `provenance` | 来源坐标。`kb_chunk`：`{doc_id, chunk_id, title}`；`web`：`{url, title, fetched_at}`，`url` 即 web 去重键 |
| `score` | 该路原始检索分：仅供展示；跨路分数不可比，融合只看序位 |
| `raw_text` | 证据原文：引用闸门的唯一裁决依据，禁止摘要/改写后回填 |
| `citation_id` | 本次回答内稳定引用号：`K-<hash8>`（私库）/ `W-<hash8>`（网络）；答案只允许引用它 |

```json
{"citation_id":"K-3f9a12c4","source_type":"kb_chunk",
 "provenance":{"doc_id":"d-102","chunk_id":"d-102#7","title":"…"},
 "score":0.82,"raw_text":"…原文…"}
```

## ② Searcher 工具契约

两个检索工具，输出同构（Evidence 列表）；不融合、不重排——融合是 Reader 的职责。

**KB 检索工具 `kb_search`**（复用 RAG_sec 既有能力：Qdrant 向量 + 全文/关键词）

```json
// 输入
{"query":"…","top_k":10,"mode":"vector | keyword"}
// 输出
{"evidence":[Evidence…],"meta":{"latency_ms":12,"index_version":"…"}}
```

**Web 搜索工具 `web_search`**（Tavily，`TAVILY_API_KEY` 环境变量）

```json
// 输入
{"query":"…","top_k":10,"time_range":"any | year | month | week | day"}
// 输出
{"evidence":[Evidence…],"meta":{"latency_ms":860,"provider":"tavily"}}
```

约定：单工具失败返回 `{"evidence":[],"error":"…"}`，不向编排层抛异常（可用性隔离）。

## ③ Reader 融合策略（三路 RRF，私库优先）

- 三路召回：`kb_search(vector)`、`kb_search(keyword)`、`web_search`；KB 两路各取 top-20、Web 取 top-10 进融合池。
- RRF：`rrf(d) = Σ 1/(k + rank_i(d))`，`k = 60`（标准值，常量）。
- 私库优先：融合分乘来源权重 `w(kb_chunk)=1.0`、`w(web)=0.7`；同分时 kb_chunk 排前。取"排序偏向"而非"硬屏蔽"——私库无命中时网络证据自然排前。
- 去重：KB 按 `chunk_id`、Web 按规范化 URL；重复证据保留最高分。
- 截断：融合后取 top-8（默认）组装生成上下文。

## ④ 引用闸门（Citation Gate）

规则：**结论必须能在被引证据的原文 `raw_text` 中定位，否则拒答。**

1. 生成约束：每句结论必须挂 `[citation_id]`；无证据支撑的句子不允许输出。
2. 逐条校验：（a）机检——结论中的数字/专名/关键断言能在被引 `raw_text` 中逐字或近义定位；（b）语义复检——LLM 判定结论确由被引原文支持。任一不过即作废。
3. 处置：作废后携带失败原因重试一次（上限 1 次，禁止循环重生）；仍失败 → 拒答。
4. 输出：
   - 通过：`{"status":"answered","answer":"…[K-3f9a12c4]…","citations":[Evidence…]}`
   - 拒答：`{"status":"refused","reason":"citation_gate_failed","unsupported_claims":["…"]}`

## ⑤ 评测方案（三组消融）

同一固定问题集、同一参数，只切换检索通道：

| 组 | 配置 |
| --- | --- |
| A 纯私库 | 只开 KB 两路（vector + keyword），Web 关闭 |
| B 纯网络 | 只开 Web，KB 关闭 |
| C 融合 | 三路全开（本设计的默认形态） |

指标（每组同算）：

- **Recall@K**：K ∈ {5, 10, 20}
- **MRR**：首个命中证据的倒数排名
- **引用准确率**：被引证据确实支持对应结论的比例（抽样人工 + LLM 辅助判定）
- **拒答准确率**：证据不足题正确拒答的比例（同时统计应答题的误拒率）
- **答案正确率**：对照金标准答案评分

数据集与验收：`eval/` 维护固定问题集（必须包含"证据不足应拒答"样本）；每组跑 3 次取均值；
**验收线：C 的五项指标均不低于 A、B，拒答准确率不劣化。**

## 不做的范围（Non-goals）

以下一律不实现，需求评审以此为准拒绝：

- **辩论拓扑**：不做多智能体辩论 / 论证图（MultiAgentIR 的 debate 结构不迁）。
- **多知识库泛化**：只服务单一私库，不做多 KB 路由、多租户、权限隔离。
- **代码/表格解析**：不解析代码结构与表格，一律按纯文本切片。
- **前缀 UI**：不实现；顶层 `frontend/` 仅占位。
- **迁移期不新增功能、不做顺手重构**（沿用现行纪律）。