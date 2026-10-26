# local-kb-v1：真实本地知识库测评

60 个固定问题，16 份仓库原文；标注为源文片段锚定的候选集，`human_verified=false`，不是公开榜单或人工金标准。中文题改编自旧候选集，新增英文题；旧冻结件不变。计划、指标和验收边界见 [测评计划](../../../docs/local-kb-evaluation-plan.md)。

## 执行

仓库根使用项目 `.venv`，根 `.env` 保存本地模型与云凭证（忽略，不提交）。先启动 PostgreSQL、Redis、Qdrant。不要在测试库执行会清表的 KE integration fixtures。

```powershell
.venv/Scripts/python.exe -X utf8 -m eval.local_kb_setup
.venv/Scripts/python.exe -X utf8 -m pytest tests_bridge/test_local_kb_eval.py -q
```

setup 只创建命名评测库并运行既有迁移，启动回环端口 8002 的真实 KE API 与隔离的 solo Worker，上传固定原件，等待入库并审计。生产库、8001 API、用户文档保持不变。进程、日志、原文 UUID 映射和存储位于忽略目录 `.env.run/local-eval/`。测试服务有随机实例身份与源码/资源指纹，上传前拒绝连接不匹配的已有服务。

确认 `audit` 中未映射要点为零，文档/索引一致后，将测量代码与冻结数据提交并保持工作区干净。正式运行：

```powershell
.venv/Scripts/python.exe -X utf8 -m eval.local_kb --phase all --output eval/results/local-kb-v1.YYYYMMDD-HHMMSS
```

也可先运行 `--phase retrieval`，随后同一 output 运行 `--phase agents`；源码、模型、冻结数据及索引指纹一致时才允许续跑。每阶段前后审计 PostgreSQL/Qdrant，不允许测量中换库。每次模型调用均为真实云请求，会产生 token 使用；失败保留，不用 fake 兜底。

## 结果

- metadata.json：代码 SHA、模型/权重指纹、候选集与语料哈希、依赖、硬件、预算；不含凭证。
- retrieval.jsonl：每题每次三路实际检索结果、完整标注片段的要点命中和 HTTP 耗时。
- agents.jsonl：两个真实 loop 的逐题回答、claims、工具轨迹、证据、token 与故障。
- summary.json：分层指标、查询级 bootstrap 区间、重复一致性、停止原因与已知用量。
- audit.json / post_audit.json：原文绑定对应的 1,892 个 child chunks（本次实际值，后续以审计为准）、Qdrant 身份与成员指纹；原文不通过人工拆页构造更容易的候选库。

原始结果位于忽略的 eval/results/；最终报告另存 docs/。可以在简历报告自建固定集、证据召回、真实延迟、预算与失败分析，不得将引用 ID 有效性或同模型内部闸门称为人工答案准确率。召回率是完整标注片段在目标来源检索文本中的覆盖，可能低估正确转述或跨 chunk 证据。多来源全部覆盖单列，不能用“命中任一来源”替代。
