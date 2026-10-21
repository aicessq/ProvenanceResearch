# 三个 Deep Research 项目的可迁移设计

日期：2026-10-21。性质：源码调研与候选方案，**没有实现新功能，也不改变路线图验收状态**。对照本地当前源码及已有评测记录；未调用本项目付费云服务，未复跑历史 live 评测。

## 结论

三个项目均有参考价值。建议顺序为：**QX 的显式知识缺口循环 → Skywork 的委派契约 → Open Deep Research 的 Supervisor 对照实验**。保留本项目 Evidence v2、Source Registry、ToolExecutor、Citation Gate、共享预算和 SSE v1，不替换整套框架。

近期工作应服务于 P3d 质量改进与 P4 重新验收。分层并行是候选扩展，需要先确认阶段前置条件与范围；本次调研不构成实施批准。不引入 Skywork 的自演进、任意代码执行或额外浏览器能力。

## 核查版本

通过 GitHub API 读取默认分支 HEAD、archived 和 license 元数据，并查看对应源码。以下固定提交用于复查，不能将未来 main 的行为视为相同。

| 项目 | 核查提交 | 许可与状态 | 一手入口 |
| --- | --- | --- | --- |
| QX Agents Deep Research | `5e7f4b2321b20bf04c72a405688ab9980887c603` | Apache-2.0；未归档 | [仓库](https://github.com/qx-labs/agents-deep-research/tree/5e7f4b2321b20bf04c72a405688ab9980887c603) |
| Skywork DeepResearchAgent | `5e3c95d14266f8c4aa6a5deae1fe165c7cd1b87b` | MIT；未归档 | [仓库](https://github.com/SkyworkAI/DeepResearchAgent/tree/5e3c95d14266f8c4aa6a5deae1fe165c7cd1b87b) |
| Open Deep Research | `1b7d2e80db9faa586165c60e09096dbbfd483a64` | MIT；已归档 | [仓库](https://github.com/langchain-ai/open_deep_research/tree/1b7d2e80db9faa586165c60e09096dbbfd483a64) |

QX 已消歧为 `qx-labs/agents-deep-research`。Skywork 当前 README 已将重心描述为 RSPL/SEPL、自演进及资源生命周期，不能只依据旧简介判断整个框架的适用性。Open 的 GitHub 页面注明 2026-08-21 归档，适合锁提交参考设计，后续维护需自行承担。参考：[Skywork README](https://github.com/SkyworkAI/DeepResearchAgent/blob/5e3c95d14266f8c4aa6a5deae1fe165c7cd1b87b/README.md)、[Open 归档提示](https://github.com/langchain-ai/open_deep_research)。复制代码时需保留对应许可证与必要版权声明；本轮未复制业务代码。

## 本项目已经有什么

| 能力 | 源码事实 | 尚需补足的地方 |
| --- | --- | --- |
| 证据驱动追加检索 | [AgentLoop](../agent/loop.py) 每轮向 planner 提供问题和已有证据，由 tool_calls 决定下一步 | 没有独立、持久的 gap 列表；证据摘要每条仅 200 字符，没把来源范围、错误观察与已尝试查询完整反馈给 planner |
| 分层与并行 | [旧 hierarchical graph](../researcher/deep_research_system/app/graphs/hierarchical_graph.py) 有拆问、并行 search/reader 和 critic 补搜 | [新生产桥](../researcher/deep_research_system/app/services/agentic_service.py) 构建单个 AgentLoop，内部工具按序执行；旧图不等于新 Evidence/预算契约已贯通 |
| 引用闸门 | [CitationGate](../agent/citation_gate.py) 验证登记、scope、数字/专名和语义支持 | 验证失败后仅泛化提示 writer 修正，仍使用同批 Reader 证据；失败原因未驱动补搜 |
| 预算和事件 | [Budget](../agent/budget.py) 有轮数/工具/token/deadline；AgentLoop 发 trace，由服务转 SSE | 并行委派需要新增全局预算预留/结算，不能给每个 Worker 一份完整预算 |
| 可复现评测 | [eval/pipelines.py](../eval/pipelines.py) 实际 A=KB-only、B=fixed mixed、C=agentic | 当前没有 Supervisor 实验条件；不要套用路线图其他段落的字母定义覆盖冻结件 |

另有两个需在 P3d 改进时覆盖的停止语义：planner JSON 解析失败当前变成空 tool_calls；循环轮数耗尽后 stop_reason 为空也会记 sufficient_evidence。两者都不能作为可靠的“缺口已填满”信号。本次仅记录，未修改。

历史质量依据来自 [decisions.md 的 2026-10-12 P4 首轮记录](decisions.md)：162 次运行零 error，但误拒率 A/B/C 为 0.4286/0.4762/0.381，机械答案分为 0.3095/0.2976/0.381，未达冻结门槛；记录将 83 次拒答均归因为 citation_gate_failed。金标准当时 verified=0，机械分只能作为方向信号；这不是本次重跑结果，也不能直接外推到后来切换的 mimo 模型。路线图概览与追加记录存在更新时间差异，不能依据概览宣称 P4 已完成。

## 1. QX：最适合先借鉴

核查源码：[knowledge_gap_agent.py](https://github.com/qx-labs/agents-deep-research/blob/5e7f4b2321b20bf04c72a405688ab9980887c603/deep_researcher/agents/knowledge_gap_agent.py)、[iterative_research.py](https://github.com/qx-labs/agents-deep-research/blob/5e7f4b2321b20bf04c72a405688ab9980887c603/deep_researcher/iterative_research.py)、[deep_research.py](https://github.com/qx-labs/agents-deep-research/blob/5e7f4b2321b20bf04c72a405688ab9980887c603/deep_researcher/deep_research.py)。

上游将缺口评估与工具选择拆开；KnowledgeGapOutput 返回 research_complete 和 outstanding_gaps，迭代器据此选择后续动作，并记录每轮缺口、调用与发现。DeepResearcher 负责大纲及章节研究。这比本项目仅以空 tool_calls 判定可作答更明确。

候选接法：在现有 AgentLoop 中维护结构化缺口，先不新增一整套 SDK 或多套 Agent。建议字段为 gap_id、question/section、required_scope、supporting_citation_ids、attempted_queries、status 和 completion_criterion；字段是本项目提案，并非 QX 原有完整 schema。类型校验要拒绝“未完成却没有 gaps”的矛盾状态。

循环建议：`问题/章节 → 缺口评估 → 现有五工具 → EvidenceStore 登记 → 更新缺口 → 充分则生成`。Citation Gate 的失败按原因路由：缺正文则 source_fetch/evidence_read，缺支持则补搜，表述越界则缩小 claim；安全违规仍拒绝。所有动作消耗同一预算，不能额外送一轮免费检索。

不要照搬全历史字符串、模型自报完成和章节各自时间上限。内部摘要不是原始证据；缺口必须关联登记 citation_id，且任务全局 deadline/token/call 上限始终优先。QX 的本地模型选项也不适用于本项目生产约束。

## 2. Skywork：借鉴任务契约，暂缓框架迁移

核查入口：[planning_agent.py](https://github.com/SkyworkAI/DeepResearchAgent/blob/5e3c95d14266f8c4aa6a5deae1fe165c7cd1b87b/src/agent/planning_agent.py)、[AgentBus](https://github.com/SkyworkAI/DeepResearchAgent/blob/5e3c95d14266f8c4aa6a5deae1fe165c7cd1b87b/src/interaction/bus.py)。当前规划输出有 PlanDecision/SubTaskDispatch，真正调度在 AgentBus，适合参考规划与执行的边界。用户所述历史分层目录可在 [固定旧版本](https://github.com/SkyworkAI/DeepResearchAgent/tree/4acd4c704ea109743f9c6390e2116923f4055693/src/agent) 复查；本轮仅核查其目录与版本，未逐行审计历史实现。

本项目收益在于把旧图的 sub_questions 变成可验收的研究任务。建议输入包含 task_id、parent_id、gap_ids、depends_on、allowed_tools、budget_slice、completion_criteria；结果包含 status、evidence_ids、unresolved_gaps、errors、usage。上述是候选契约，不宣称当前已有。

Worker 先限定为研究只读能力，经现有 ToolExecutor 调用，不能绕过云出站授权、来源登记和引用闸门。结果应返回证据 ID 及不足项，摘要另存；不能只返回一段自然语言“完成了”。Supervisor 根据程序验证过的完成条件汇总，有依赖的子任务顺序执行，无依赖的子任务才可并行。

不建议引入上游自演进/优化器/资源协议体系：超出当前批准目标，而且会引入第二套配置、生命周期与追踪实现。当前 planner 还存在 LLM 异常时构造 is_done=True 并随后 finalize(success=True) 的完成语义风险，不应照搬。现有旧图可以作为行为参考，但不能未经新契约与回归验证直接改接生产。

## 3. Open Deep Research：用于比较架构的成熟参照

核查源码：[deep_researcher.py](https://github.com/langchain-ai/open_deep_research/blob/1b7d2e80db9faa586165c60e09096dbbfd483a64/src/open_deep_research/deep_researcher.py)、[state.py](https://github.com/langchain-ai/open_deep_research/blob/1b7d2e80db9faa586165c60e09096dbbfd483a64/src/open_deep_research/state.py)、[configuration.py](https://github.com/langchain-ai/open_deep_research/blob/1b7d2e80db9faa586165c60e09096dbbfd483a64/src/open_deep_research/configuration.py)。

可借鉴研究 brief、Supervisor 的 ConductResearch 委派、Researcher 子图、并行研究与结果压缩。这为“单 Agent 是否值得升级为 Supervisor”提供可复查参照。

本项目应让 Worker 输出保留 evidence_ids 与原始 locator，压缩仅供调度与写作导航，事实支持仍回到 EvidenceStore。并发上限不是总预算；planning、压缩、重试、验证、重生成都必须计入全局 token/API 费用。

失败处理不可照搬：所核查 supervisor_tools 中存在 `is_token_limit_exceeded(...) or True`，使任意异常都结束研究阶段；结合后续报告生成可能掩盖未完成任务。本项目应显式区分 failed/partial/completed，并保留来源故障；不能把异常文本当证据或自动当成功。

## 建议的实施与验收顺序（尚未实施）

1. **P3d：显式缺口与停止判定。** 先在单 Agent 中增加缺口状态、工具错误观察和结构化输出校验；测试“只缺论文正文→定向 fetch/read”“证据充分不再搜”“非法 planner 输出不冒充充分”“耗尽仍有 gap 不记充分”。保留未知工具/循环/取消/越权/伪证据的拒绝行为。
2. **P3d/P4：验证反馈闭环与部分作答。** 区分缺证据、引用范围错误和表达过度；将验证结果反馈到有限修复动作。部分作答须从通过验证的 claims 重建正文并再核验，不能只过滤 claims 数组却留下未支持正文。精确数值、OCR 和视觉结论仍遵守原闸门；不放宽语义阈值换取低误拒。
3. **P4：先测收益。** 固定数据、模型/provider、索引、prompt 版本和预算，做现有单 Agent、显式 gap 单 Agent、gap+验证反馈的消融；每条件至少沿用冻结件三次重复。不得用更换模型或增加预算冒充架构增益。
4. **阶段验收及范围确认后：Supervisor 候选实验。** 与改进后的单 Agent 比较，保持同源同模型同全局工具/token/deadline 上限，并报告实际消耗。采用预算预留/结算与受控并发，测试某 Worker 失败隔离、父任务取消、并发去重和 evidence 合并；不复制完整预算给每个 Worker。

评测保留 A/B/C 既有定义和冻结件，新增实验应另建版本，不改写历史基线。报告答案正确率、引用准确率/覆盖、误拒/拒答、Recall@k、p95、token/费用、来源故障和预算合规，另列缺口闭合率、重复搜索率、partial 比例。缺口闭合须按 completion_criteria 和真实证据判断，不能只数 LLM 标记 closed。

继续遵守 [roadmap.md](roadmap.md) 的前置与验收。历史金标准 verified=false 的样本需要人工核验后才宜用于最终质量裁决；不得事后放宽 P4 门槛。没有公平对照结果前，不宣称分层并行更准、更快或更便宜。

## 本轮范围与验证

仅新增本调研文件，并在 decisions.md 追加调研结论及保留理由；没有修改生产代码、配置、依赖、路线图或评测冻结件。对应验证为离线仓库契约检查、本文本地相对链接检查及 diff 空白检查；不以文档检查替代功能验收。
