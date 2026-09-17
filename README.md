# research_agent

私库 + 网络双源检索问答系统：所有结论必须能落到证据原文（引用闸门），否则拒答。

由两个既有项目合并而来（2026-09-17 原样搬入，零代码改动）：

| 目录 | 来源 | 职责 |
| --- | --- | --- |
| `knowledge_engine/` | RAG_sec | 私库侧：PostgreSQL + Redis + Qdrant + FastAPI/Celery，入库与检索 |
| `researcher/` | MultiAgentIR_LangGraph | 检索编排侧：Searcher 工具与 Reader 融合的归宿 |
| `frontend/` | — | 占位（非目标：不实现界面） |
| `eval/` | — | 占位：三组消融评测（纯私库 / 纯网络 / 融合） |
| `tests_bridge/` | — | 占位：跨组件桥接测试 |
| `docs/` | — | 设计文档与决策记录 |

- 设计（证据模型 / 工具契约 / 融合 / 引用闸门 / 评测）：[`docs/design.md`](docs/design.md)
- 决策记录（保留了什么、改了什么、为什么）：[`docs/decisions.md`](docs/decisions.md)
- 迁移路线图与逐阶段验收：[`docs/roadmap.md`](docs/roadmap.md)
- 测试命令与已记录的基线：[`docs/testing.md`](docs/testing.md)

## 快速开始（基础设施）

```bash
cp .env.example .env   # 填 LLM_* 与 TAVILY_API_KEY
docker compose up -d   # postgres:16 + redis:7 + qdrant
```

## 本轮状态

基线轮：两个子系统的测试与前端构建首次实际跑通并记录基线（`docs/testing.md`）、
迁移路线图成文（`docs/roadmap.md`）、根 `.env.example` 补齐、CI 第一版落地。
仍然**没有做任何业务代码改动与接线**（迁移期纪律：不新增功能、不顺手重构）。