from __future__ import annotations

from app.schemas.state import ResearchState
from app.schemas.task import TaskSpec
from app.topology.hierarchical import HierarchicalTopology
from app.topology.debate import DebateTopology


class StubRunner:
    def __init__(self, final_report: dict, claim_graph: list[dict], validation: dict | None = None) -> None:
        self.final_report = final_report
        self.claim_graph = claim_graph
        self.validation = validation or {"valid": True, "score": 92, "issues": []}
        self.calls: list[tuple[ResearchState, object]] = []

    async def run(self, state: ResearchState, on_event=None) -> ResearchState:
        self.calls.append((state, on_event))
        if on_event:
            on_event({"type": "stage_start", "agent": "planner", "progress": 10})
            on_event({"type": "report_update", "agent": "writer", "progress": 97, "output": self.final_report})
        state.plan = [{"id": "sq_1", "question": state.task.user_query}]
        state.claim_graph = self.claim_graph
        state.final_report = self.final_report
        state.current_stage = "completed"
        state.progress = 100
        return state


def test_hierarchical_topology_delegates_to_graph(monkeypatch) -> None:
    runner = StubRunner(final_report={"title": "hierarchical"}, claim_graph=[{"claim_id": "c1"}])
    topo = HierarchicalTopology()
    monkeypatch.setattr(topo, "_graph", runner)

    state = ResearchState(task=TaskSpec(task_id="task_1", user_query="AI market"))

    result = __import__("asyncio").run(topo.execute(state))

    assert result.final_report == {"title": "hierarchical"}
    assert runner.calls


def test_debate_topology_delegates_to_graph(monkeypatch) -> None:
    runner = StubRunner(final_report={"title": "debate"}, claim_graph=[{"claim_id": "c2"}])
    topo = DebateTopology()
    monkeypatch.setattr(topo, "_graph", runner)

    state = ResearchState(task=TaskSpec(task_id="task_2", user_query="Should we adopt AI?", task_type="open_question"))

    result = __import__("asyncio").run(topo.execute(state))

    assert result.final_report == {"title": "debate"}
    assert runner.calls
