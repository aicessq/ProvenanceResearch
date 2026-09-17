from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.agents.base import BaseAgent
from app.graphs.events import emit, wrap_agent_name
from app.schemas.state import ResearchState
from app.topology.base import EventCallback


@dataclass(slots=True)
class AgentNodeRunner:
    agent: BaseAgent
    stage_name: str
    progress_start: int | None = None
    progress_complete: int | None = None
    wrapped_agent_name: str | None = None
    completion_output: Callable[[dict, ResearchState], dict] | None = None

    async def run(self, state: ResearchState, on_event: EventCallback = None) -> dict:
        callback = on_event
        if self.wrapped_agent_name:
            callback = wrap_agent_name(on_event, self.wrapped_agent_name)

        if self.progress_start is not None:
            state.current_stage = self.stage_name
            state.progress = self.progress_start
            emit(on_event, {
                "type": "stage_start",
                "agent": self.stage_name,
                "progress": self.progress_start,
            })

        result = await self.agent.run(state, on_event=callback)

        if self.progress_complete is not None:
            output = result if self.completion_output is None else self.completion_output(result, state)
            emit(on_event, {
                "type": "stage_complete",
                "agent": self.stage_name,
                "progress": self.progress_complete,
                "output": output,
            })
            state.progress = self.progress_complete

        return result
