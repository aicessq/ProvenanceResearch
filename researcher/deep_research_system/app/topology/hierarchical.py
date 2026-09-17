from __future__ import annotations

from app.graphs.events import wrap_agent_name as _wrap_agent_name
from app.schemas.state import ResearchState
from app.topology.base import BaseTopology, EventCallback


class HierarchicalTopology(BaseTopology):
    name = "hierarchical"

    def __init__(self) -> None:
        self._graph = None

    def _get_graph(self):
        if self._graph is None:
            from app.graphs.hierarchical_graph import build_hierarchical_graph

            self._graph = build_hierarchical_graph()
        return self._graph

    async def execute(self, state: ResearchState, on_event: EventCallback = None) -> ResearchState:
        return await self._get_graph().run(state, on_event=on_event)
