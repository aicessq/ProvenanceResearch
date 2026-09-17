from __future__ import annotations

from dataclasses import dataclass

from app.graphs.debate_graph import build_debate_graph
from app.graphs.hierarchical_graph import build_hierarchical_graph
from app.schemas.state import ResearchState
from app.topology.base import EventCallback


@dataclass(slots=True)
class GraphRunner:
    hierarchical: object
    debate: object

    async def run(self, topology_name: str, state: ResearchState, on_event: EventCallback = None) -> ResearchState:
        if topology_name == "debate":
            return await self.debate.run(state, on_event=on_event)
        return await self.hierarchical.run(state, on_event=on_event)


def build_graph_runner() -> GraphRunner:
    return GraphRunner(
        hierarchical=build_hierarchical_graph(),
        debate=build_debate_graph(),
    )
