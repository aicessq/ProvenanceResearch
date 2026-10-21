# Agent 机制与问题对应表

日期：2026-10-21。实施分支：`dev`。此文按实际交付追加，质量收益须另经 P4 真实对照证明。

## 规划校验与真实停止原因

**解决的问题**：坏 JSON、缺 tool_calls 等输出曾被当成“可以回答”；轮数耗尽或重复无进展后，成功写作又覆盖停止原因，使运行轨迹看起来像证据充分。

**加入的机制**：校验规划对象和工具调用结构；非法输出显式拒绝并记录 invalid_planner_output，不调用 writer。规划前后检查预算；轮数耗尽记录 budget_exhausted。有证据且仍能安全完成写作时允许回答，但保留检索真实停止原因。

**保留的约束**：不增加公开 StopReason 枚举，错误细分放 refusal_reason/error 事件；未知工具与非法业务参数仍由 ToolExecutor 拒绝。已有引用闸门不放宽。

**证据**：`agent/tests/test_control_flow.py` 覆盖坏结构、耗尽后作答保留原因、超时前不启动规划；原 loop 无进展断言同步改为检查真实原因，不改变有据作答要求。

后续知识缺口、验证反馈、部分作答与消融接入完成后在本文分别记录，不预标为已完成。


## 显式缺口账本与调用反馈

**解决的问题**：规划只能看到短证据摘要，缺少来源范围、已试查询及错误；“搜索了很多次”不等于研究问题已解决。

**加入的机制**：GapLedger 保存最多 12 项 question/required_scope/completion_criterion、支持引用及尝试记录；条件建立后不可改写，删项不能消除未解缺口。请求 resolved 必须让条件作为 claim 经过现有 Citation Gate。规划输入携带 source_id、scope、历史调用/错误和预算；gap_ids→call_id→evidence_ids 形成追踪链，复用 plan/tool_result 事件并在任务结果增加 gaps 字段，公开回答状态不变。

**保留的约束**：账本不是新证据，不能将摘要补写成正文；没有语义支持或范围不足不闭合。旧仅 tool_calls 的规划格式仍可读，供旧消费者/固定对照使用，但不凭空声称具有缺口覆盖度。新提示词明确要求结构化 gaps。

**必要接线**：source_fetch 可从已登记 Evidence 获取来源身份，再走原逐跳获取防护；模型仍只能提供 source_id。获取时间记录实际时间。arXiv 的 /abs/ 页面不能按 fulltext 返回，报 fulltext_unavailable；PDF 正文提取未因此自动完成。

**证据**：test_gaps.py 覆盖缺正文定向读取、摘要不能闭合全文、工具失败反馈、删项/改条件、伪引用/语义不支持、搜索证据到真实 SourceFetchTool 的录制 HTTP 接线。
