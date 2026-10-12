#!/usr/bin/env python3
"""UI 联调冒烟服务器（**FAKE 运行时**，仅用于前端联调/截图，不是生产入口）。

生产启动方式是 `uvicorn main:app`（缺云配置时任务显式失败，见 AGENTS.md）；
本脚本显式注入脚本 LLM + eval 语料检索的假运行时，仅为验证前端三栏/时间线/
证据面板与 /api/v1 + SSE 的联调。**其产出不是评测结论，也不是真实模型答案。**

用法：
    python3 scripts/ui_smoke_server.py            # 127.0.0.1:8000
    cd frontend && npm run dev                     # 另一终端，5173 代理 /api → 8000
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "researcher" / "deep_research_system"))

from agent.budget import Budget  # noqa: E402
from app.api import routes_v1  # noqa: E402
from app.services.agentic_service import AgenticRuntime, AgenticTaskService  # noqa: E402
from app.services.sse_v1 import InMemoryEventLog  # noqa: E402
from eval.corpus_search import CorpusIndex  # noqa: E402
from eval.pipelines import EvalKBSearchTool  # noqa: E402
from eval.runner import FakeEvalLLM, YesChecker  # noqa: E402
from evidence.store import EvidenceStore  # noqa: E402
from tools import ToolExecutor  # noqa: E402

BANNER = "=" * 72


def build_fake_runtime() -> AgenticRuntime:
    corpus = CorpusIndex(REPO_ROOT / "eval" / "corpus")
    store = EvidenceStore()
    llm = FakeEvalLLM()
    return AgenticRuntime(
        llm=llm,
        executor=ToolExecutor(tools=[EvalKBSearchTool(corpus, store, "ui-smoke+local-bigram-v1")]),
        store=store,
        budget=Budget(),
        semantic_checker=YesChecker(),
    )


def main() -> None:
    import uvicorn

    print(BANNER)
    print("!! UI 联调冒烟模式：FAKE LLM + eval 语料检索（仅测试，不是生产入口）")
    print("!! 生产请用 `uvicorn main:app`；缺云配置时任务显式失败")
    print(BANNER)

    routes_v1._service = AgenticTaskService(
        runtime_factory=build_fake_runtime,
        event_log=InMemoryEventLog(),
    )
    from main import app

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")


if __name__ == "__main__":
    main()
