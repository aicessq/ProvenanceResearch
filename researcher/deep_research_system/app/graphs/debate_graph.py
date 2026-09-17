from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents.critic import CriticAgent
from app.agents.debate import DebateAgent, SynthesizerAgent
from app.agents.planner import PlannerAgent
from app.agents.validator import ValidatorAgent
from app.agents.writer import WriterAgent
from app.core.config import get_config
from app.graphs.events import emit, wrap_agent_name
from app.graphs.graph_state import GraphContext
from app.model_pool.client import LLMClient
from app.model_pool.key_pool import APIKeyPool
from app.model_pool.registry import ModelRegistry
from app.model_pool.router import FallbackRouter
from app.schemas.state import ResearchState
from app.topology.base import EventCallback

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DebateGraphRunner:
    planner: PlannerAgent
    critic: CriticAgent
    synthesizer: SynthesizerAgent
    writer: WriterAgent
    validator: ValidatorAgent
    debate_factory: Any
    graph: Any = field(init=False, repr=False)

    def __post_init__(self) -> None:
        graph = StateGraph(GraphContext)
        graph.add_node("planner", self._planner)
        graph.add_node("debate", self._debate)
        graph.add_node("critic", self._critic)
        graph.add_node("synthesizer", self._synthesizer)
        graph.add_node("writer", self._writer)
        graph.add_node("validator", self._validator)
        graph.add_node("repair_writer", self._repair_writer)

        graph.add_edge(START, "planner")
        graph.add_edge("planner", "debate")
        graph.add_edge("debate", "critic")
        graph.add_edge("critic", "synthesizer")
        graph.add_edge("synthesizer", "writer")
        graph.add_edge("writer", "validator")
        graph.add_conditional_edges(
            "validator",
            self._route_after_validator,
            {"repair_writer": "repair_writer", "end": END},
        )
        graph.add_edge("repair_writer", "validator")
        self.graph = graph.compile()

    async def run(self, state: ResearchState, on_event: EventCallback = None) -> ResearchState:
        context: GraphContext = {
            "state": state,
            "on_event": on_event,
            "repair_attempt": 0,
            "last_validation": {},
            "last_plan_result": {},
        }
        result = await self.graph.ainvoke(context)
        return result["state"]

    async def _planner(self, context: GraphContext) -> GraphContext:
        state = context["state"]
        on_event = context.get("on_event")
        state.current_stage = "planner"
        state.progress = 10
        emit(on_event, {"type": "stage_start", "agent": "planner", "progress": 10})
        plan_result = await self.planner.run(state, on_event=on_event)
        state.plan = plan_result.get("sub_questions", [])
        context["last_plan_result"] = plan_result
        emit(on_event, {"type": "stage_complete", "agent": "planner", "progress": 20, "output": plan_result})
        return context

    async def _debate(self, context: GraphContext) -> GraphContext:
        state = context["state"]
        on_event = context.get("on_event")
        state.current_stage = "debate"
        state.progress = 30

        plan_result = context.get("last_plan_result", {})
        hypotheses = plan_result.get("hypotheses", [])
        if not hypotheses:
            hypotheses = [sq.get("question", "") for sq in state.plan[:3]]
        if not hypotheses:
            hypotheses = [state.task.user_query]

        tasks = []
        branch_names = []
        for i, hypothesis in enumerate(hypotheses):
            branch = f"h_{i}"
            branch_names.append(branch)
            emit(on_event, {"type": "stage_start", "agent": branch, "progress": 30})
            agent = self.debate_factory(hypothesis, branch)
            tasks.append(agent.run(state, on_event=wrap_agent_name(on_event, branch)))

        results = await asyncio.gather(*tasks, return_exceptions=True) if tasks else []
        for branch, result in zip(branch_names, results):
            if isinstance(result, Exception):
                logger.error(f"Debate {branch} failed: {result}")
                state.errors.append({"stage": "debate", "branch": branch, "error": str(result)})
                emit(on_event, {"type": "stage_complete", "agent": branch, "progress": 50})
                continue
            state.debate_results[branch] = result
            for ev in result.get("evidence", []):
                url = ev.get("source_url", "")
                if url and url not in state.source_registry:
                    state.source_registry[url] = {"url": url, "title": "", "source_type": "unknown"}
            emit(on_event, {
                "type": "subtask_complete",
                "agent": branch,
                "subtask_id": branch,
                "message": f"{branch} 假设检验完成",
                "output": result,
            })
            emit(on_event, {"type": "stage_complete", "agent": branch, "progress": 50})
        return context

    async def _critic(self, context: GraphContext) -> GraphContext:
        state = context["state"]
        on_event = context.get("on_event")
        state.current_stage = "critic"
        state.progress = 55
        emit(on_event, {"type": "stage_start", "agent": "critic", "progress": 55})
        critique = await self.critic.run(state, on_event=on_event)
        state.critiques.append(critique)
        emit(on_event, {"type": "stage_complete", "agent": "critic", "progress": 65, "output": critique})
        return context

    async def _synthesizer(self, context: GraphContext) -> GraphContext:
        state = context["state"]
        on_event = context.get("on_event")
        state.current_stage = "synthesizer"
        state.progress = 70
        emit(on_event, {"type": "stage_start", "agent": "synthesizer", "progress": 70})
        synthesis = await self.synthesizer.run(state, on_event=on_event)
        state.analyses.append(synthesis)
        if isinstance(synthesis, dict):
            state.claim_graph = synthesis.get("hypothesis_assessment", [])
        emit(on_event, {"type": "stage_complete", "agent": "synthesizer", "progress": 75, "output": synthesis})
        return context

    async def _writer(self, context: GraphContext) -> GraphContext:
        state = context["state"]
        on_event = context.get("on_event")
        state.current_stage = "writer"
        state.progress = 85
        emit(on_event, {"type": "stage_start", "agent": "writer", "progress": 85})
        report = await self.writer.run(state, on_event=on_event)
        state.final_report = report
        emit(on_event, {
            "type": "stage_complete",
            "agent": "writer",
            "progress": 90,
            "output": {"title": report.get("title", ""), "executive_summary": report.get("executive_summary", "")},
        })
        return context

    async def _validator(self, context: GraphContext) -> GraphContext:
        state = context["state"]
        on_event = context.get("on_event")
        state.current_stage = "validator"
        state.progress = 95
        emit(on_event, {"type": "stage_start", "agent": "validator", "progress": 95})
        validation = await self.validator.run(state, on_event=on_event)
        emit(on_event, {"type": "stage_complete", "agent": "validator", "progress": 98, "output": validation})
        context["last_validation"] = validation
        return context

    async def _repair_writer(self, context: GraphContext) -> GraphContext:
        state = context["state"]
        on_event = context.get("on_event")
        attempt = context.get("repair_attempt", 0) + 1
        context["repair_attempt"] = attempt
        agent_name = f"repair_writer_{attempt}"
        emit(on_event, {"type": "stage_start", "agent": agent_name, "progress": 96, "repair_count": attempt})
        validation = context.get("last_validation", {})
        state.repair_context = validation.get("issues", [])
        report = await self.writer.run(state, on_event=wrap_agent_name(on_event, agent_name))
        state.final_report = report
        validation = await self.validator.run(state, on_event=None)
        context["last_validation"] = validation
        emit(on_event, {
            "type": "stage_complete",
            "agent": agent_name,
            "progress": 97,
            "repair_count": attempt,
            "output": validation,
        })
        emit(on_event, {"type": "report_update", "agent": "writer", "progress": 97, "output": state.final_report})
        return context

    def _route_after_validator(self, context: GraphContext) -> str:
        state = context["state"]
        on_event = context.get("on_event")
        validation = context.get("last_validation", {})
        topo_cfg = get_config().topology.get("debate", {})
        max_repair_loops = topo_cfg.get("max_repair_loops", 2)
        attempt = context.get("repair_attempt", 0)
        is_valid = validation.get("valid", False)
        score = validation.get("score", 100)
        if is_valid and score >= 85:
            state.repair_context = []
            emit(on_event, {"type": "report_update", "agent": "writer", "progress": 99, "output": state.final_report})
            state.current_stage = "completed"
            state.progress = 100
            return "end"
        if attempt < max_repair_loops:
            return "repair_writer"
        state.repair_context = []
        emit(on_event, {"type": "report_update", "agent": "writer", "progress": 99, "output": state.final_report})
        state.current_stage = "completed"
        state.progress = 100
        return "end"


def build_debate_graph() -> DebateGraphRunner:
    registry = ModelRegistry()
    key_pool = APIKeyPool()
    router = FallbackRouter(registry, key_pool)
    llm_client = LLMClient()
    return DebateGraphRunner(
        planner=PlannerAgent(router=router, llm_client=llm_client, key_pool=key_pool),
        critic=CriticAgent(router=router, llm_client=llm_client, key_pool=key_pool),
        synthesizer=SynthesizerAgent(router=router, llm_client=llm_client, key_pool=key_pool),
        writer=WriterAgent(router=router, llm_client=llm_client, key_pool=key_pool),
        validator=ValidatorAgent(router=router, llm_client=llm_client, key_pool=key_pool),
        debate_factory=lambda hypothesis, branch: DebateAgent(
            hypothesis=hypothesis,
            branch=branch,
            router=router,
            llm_client=llm_client,
            key_pool=key_pool,
        ),
    )
