# eval/（P4 前置交付物已就位：语料 + 人工金标准题目集）

本目录承载固定语料、固定问题集与（P4 的）评测 runner。当前**已有**：

- [corpus/](corpus/README.md) —— 28 篇固定语料（16 中国法律法规 + 2 NIST + 3 RFC + 7 arXiv），
  manifest/sha256/页级文本镜像/下载脚本齐备；5 篇扫描件与许可待用户裁决（见其 `LICENSES.md`）。
- [questions/](questions/README.md) —— 56 道人工金标准候选题（`verified: false`，
  等用户逐题核对）+ 离线校验脚本 + [人工核对清单](questions/REVIEW_CHECKLIST.md)。

尚无 runner、指标与结果。P4 评测协议（下文）沿用：

保留 KB-only、external-only、固定混合三组，并加入同源同模型同预算的 Agentic RAG；每组 3 次，补去 arXiv、去 OCR/vision、禁追加检索、去云 rerank 消融。数据包含外网必答、论文摘要/全文、文本/扫描/混合/含图 PDF、独立图片、多步与无据拒答题。

指标覆盖 Recall@5/10/20、MRR、引用准确率、拒答准确率、答案正确率、误拒率、工具/终止合规、来源覆盖、OCR CER/WER、视觉事实与页/区域引用准确率、p95 延迟、token/API 费用及 provider 失败/重试。检索排名在 top-8 截断前评估；正式跑分前冻结版本、标注、非回归容差、分层最低质量和成本/延迟门槛，不要求混合组所有指标同时超过每个单源。

- [评测协议](../docs/design.md#10-评测与验收)
- [P4 前置与验收](../docs/roadmap.md#p4--评测与消融)
