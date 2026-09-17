from __future__ import annotations

from app.topology.base import BaseTopology, EventCallback


def emit(on_event: EventCallback, event: dict) -> None:
    BaseTopology.emit(on_event, event)


def wrap_agent_name(on_event: EventCallback, wrapped_name: str) -> EventCallback:
    """Rename agent-level events so frontend-visible agent ids stay stable."""

    def wrapped_event(event: dict) -> None:
        agent = event.get("agent", "")
        if agent and event.get("type") in (
            "agent_model_selected", "agent_thinking", "agent_output",
            "agent_stream_token", "subtask_complete",
        ):
            event = {**event, "agent": wrapped_name}
        emit(on_event, event)

    return wrapped_event
