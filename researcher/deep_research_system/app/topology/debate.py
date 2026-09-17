from __future__ import annotations

from app.schemas.state import ResearchState
from app.topology.base import BaseTopology, EventCallback


class DebateTopology(BaseTopology):
    name = "debate"

    def __init__(self) -> None:
        self._graph = None

    def _get_graph(self):
        if self._graph is None:
            from app.graphs.debate_graph import build_debate_graph

            self._graph = build_debate_graph()
        return self._graph

    async def execute(self, state: ResearchState, on_event: EventCallback = None) -> ResearchState:
        return await self._get_graph().run(state, on_event=on_event)
