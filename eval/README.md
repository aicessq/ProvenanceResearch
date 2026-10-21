# 评测与 Agent 改进对照

更新：2026-10-21。已有 runner、指标、冻结配置和离线/历史 live 记录。**fake 只验证机制；真实质量收益仍需 live 对照及人工核验，不能因脚本跑通宣称 P4 完成。**

## 资产与入口

| 文件/目录 | 用途 |
| --- | --- |
| [corpus/](corpus/README.md) | 28 条来源清单；21 份页级镜像随仓库发布，7 条仓库外资产按清单处理 |
| [questions/](questions/README.md) | 56 道候选题，verified=false；首轮冻结其中 18 题 |
| [runner.py](runner.py) / [metrics.py](metrics.py) | A/B/C 执行与检索/引用/回答/拒答/运行指标 |
| [round1.freeze.json](baseline/round1.freeze.json) | 历史题集、版本、预算和门槛，保持不变 |
| [compare_agents.py](compare_agents.py) | 前后对照与消融入口，保存逐题结果及来源快照 |
| [agent-improvement.freeze.json](baseline/agent-improvement.freeze.json) | 固定旧 loop 提交/hash、数据指纹、三实验组和共同预算 |

当前 runner 的 A/B/C 实际含义为 **A=KB-only、B=固定混合、C=Agentic**。设计文档的其他字母体系是更广泛目标，不用于改写历史冻结件。

## 修改前后怎么比较

| 实验组 | 执行内容 |
| --- | --- |
| baseline | 固定原 loop 提交；共用当前 provider/证据/Reader/工具环境，不声称完全复现旧系统 |
| gaps | 当前停止/预算/正文安全修正与显式缺口；关闭验证反馈和最终部分作答 |
| feedback | 完整改进：缺口、验证反馈补检索、受限部分作答 |

三组同题、同模型、同来源环境、同预算，每题默认三次；相同外部请求共享首次响应，查询/来源证据/命中缓存情况写入报告。新查询仍可取得新证据，各组逻辑工具调用分别计数。保存逐题配对差值、引用与答案机械指标、误拒/拒答、p95、token、来源错误、重复调用与缺口闭合等数据。

离线自检（仓库根，Windows 建议 UTF-8 模式）：

```powershell
python -X utf8 -m pytest tests_bridge/test_p4_eval.py tests_bridge/test_agent_comparison.py tests_bridge/test_eval_accounting.py -q
python -X utf8 -m eval.compare_agents --mode fake
```

凭证和出站授权就绪后，同一入口切 live：

```powershell
python -X utf8 -m eval.compare_agents --mode live
```

需要 LLM_API_KEY（或 DEEPSEEK_API_KEY 兼容项）、模型/端点配置、TAVILY_API_KEY 及既有逐能力出站授权。arXiv 元数据接口无 API key。缺配置明确失败，不回退 fake/本地模型；凭证只放 gitignored 环境文件或已有加密配置，不写入结果。此入口从进程环境读配置，不自动加载其他电脑的 .env。

结果保存在 gitignored `eval/results/agent-improvement.<mode>.<时间>.json`。每报告记录代码版本、工作区状态、源码指纹、冻结件和实际模型身份；旧源码只在评测入口按固定提交和 hash 校验后加载，生产不走该路径。历史 A/B/C 仍可运行 `python -X utf8 eval/runner.py --mode fake`。

## 判读边界与尚未验收项

- 18×3×3 的离线对照已跑通，三组各 54 次、0 error，各自安全样例 5/5；报告 `not_a_conclusion=true`。这不是模型质量分数。
- 金标准尚未逐题人工核验；required_points 关键词覆盖仅为机械代理，引用来源命中也不等于语义正确。人工流程见 [REVIEW_CHECKLIST.md](questions/REVIEW_CHECKLIST.md)。
- 门槛沿用原冻结件，新组另报相对 baseline 的非回归判断；禁止事后改题或放宽标准。fake 不判质量门槛，live 缺人工核验也不宣称完整质量结论。
- 快照下的延迟不能直接当完整冷启动线上延迟；外部真实请求和缓存命中分开记录。当前无美元计价表/费用硬门槛，`currency_cost_unknown=true`，不宣称金额验收通过。
- 失败运行计入质量/合规分母，已知用量仍累计；失败调用/取消的未知用量明确标注，不能按零费用处理。历史零 error 结果不重写。
- OCR/vision 已有适配和离线入库契约，首轮 runner 尚无完整真实 OCR/视觉质量评测；不能把文本 Agent 对照当成多模态验收。
- 当前电脑没有所需云凭证，真实云对照、人工核验及完整 P4 验收待条件就绪。Supervisor 不在本轮实施范围。

详细机制及加入原因见 [agent-mechanisms.md](../docs/agent-mechanisms.md)，阶段标准见 [roadmap.md](../docs/roadmap.md)。
