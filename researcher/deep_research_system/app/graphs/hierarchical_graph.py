from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents.analyzer import AnalyzerAgent
from app.agents.critic import CriticAgent
from app.agents.planner import PlannerAgent
from app.agents.reader import ReaderAgent
from app.agents.searcher import SearcherAgent
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
class HierarchicalGraphRunner:
    planner: PlannerAgent
    analyzer: AnalyzerAgent
    critic: CriticAgent
    writer: WriterAgent
    validator: ValidatorAgent
    searcher_factory: Any
    reader_factory: Any
    graph: Any = field(init=False, repr=False)

    def __post_init__(self) -> None:
        graph = StateGraph(GraphContext)
        graph.add_node("planner", self._planner)
        graph.add_node("search", self._search)
        graph.add_node("reader", self._reader)
        graph.add_node("analyzer", self._analyzer)
        graph.add_node("critic", self._critic)
        graph.add_node("supplementary_search", self._supplementary_search)
        graph.add_node("writer", self._writer)
        graph.add_node("validator", self._validator)
        graph.add_node("repair_writer", self._repair_writer)

        graph.add_edge(START, "planner")
        graph.add_edge("planner", "search")
        graph.add_edge("search", "reader")
        graph.add_edge("reader", "analyzer")
        graph.add_edge("analyzer", "critic")
        graph.add_conditional_edges(
            "critic",
            self._route_after_critic,
            {"supplementary_search": "supplementary_search", "writer": "writer"},
        )
        graph.add_edge("supplementary_search", "analyzer")
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
            "supplementary_loop_count": 0,
            "last_validation": {},
            "supplementary_result": None,
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
        if plan_result.get("suggested_topology"):
            state.selected_topology = plan_result["suggested_topology"]
        emit(on_event, {"type": "stage_complete", "agent": "planner", "progress": 20, "output": plan_result})
        return context

    async def _search(self, context: GraphContext) -> GraphContext:
        state = context["state"]
        on_event = context.get("on_event")
        state.current_stage = "searcher"
        state.progress = 25
        emit(on_event, {"type": "stage_start", "agent": "searcher", "progress": 25})
        tasks = []
        sq_ids = []
        for sq in state.plan:
            sq_id = sq["id"]
            sq_ids.append(sq_id)
            agent_name = f"searcher_{sq_id}"
            searcher = self.searcher_factory()
            sq_state = state.model_copy(deep=True)
            sq_state.plan = [sq]
            emit(on_event, {"type": "stage_start", "agent": agent_name, "progress": 25})
            tasks.append(searcher.run(sq_state, on_event=wrap_agent_name(on_event, agent_name)))

        results = await asyncio.gather(*tasks, return_exceptions=True) if tasks else []
        for sq_id, result in zip(sq_ids, results):
            agent_name = f"searcher_{sq_id}"
            if isinstance(result, Exception):
                logger.error(f"Searcher failed for {sq_id}: {result}")
                state.errors.append({"stage": "searcher", "sq_id": sq_id, "error": str(result)})
                emit(on_event, {"type": "stage_complete", "agent": agent_name, "progress": 30})
                continue
            state.sub_results[sq_id] = result
            for source in result.get("sources", []):
                url = source.get("url", "")
                if url:
                    state.source_registry[url] = source
            emit(on_event, {"type": "stage_complete", "agent": agent_name, "progress": 30, "output": result})

        emit(on_event, {
            "type": "stage_complete",
            "agent": "searcher",
            "progress": 35,
            "output": {"results": list(state.sub_results.keys())},
        })
        return context

    async def _reader(self, context: GraphContext) -> GraphContext:
        state = context["state"]
        on_event = context.get("on_event")
        state.current_stage = "reader"
        state.progress = 45
        emit(on_event, {"type": "stage_start", "agent": "reader", "progress": 45})
        tasks = []
        sq_ids = []
        for sq_id, sq_data in state.sub_results.items():
            agent_name = f"reader_{sq_id}"
            reader = self.reader_factory()
            sq_state = state.model_copy(deep=True)
            sq_state.sub_results = {sq_id: sq_data}
            sq_ids.append(sq_id)
            emit(on_event, {"type": "stage_start", "agent": agent_name, "progress": 45})
            tasks.append(reader.run(sq_state, on_event=wrap_agent_name(on_event, agent_name)))

        results = await asyncio.gather(*tasks, return_exceptions=True) if tasks else []
        for sq_id, result in zip(sq_ids, results):
            agent_name = f"reader_{sq_id}"
            if isinstance(result, Exception):
                logger.error(f"Reader failed for {sq_id}: {result}")
                emit(on_event, {"type": "stage_complete", "agent": agent_name, "progress": 50})
                continue
            state.sub_results[sq_id] = {**state.sub_results[sq_id], **result}
            emit(on_event, {"type": "stage_complete", "agent": agent_name, "progress": 50, "output": result})

        emit(on_event, {
            "type": "stage_complete",
            "agent": "reader",
            "progress": 55,
            "output": {"sub_results_count": len(state.sub_results)},
        })
        return context

    async def _analyzer(self, context: GraphContext) -> GraphContext:
        state = context["state"]
        on_event = context.get("on_event")
        state.current_stage = "analyzer"
        state.progress = 60
        in_supplementary_loop = context.get("supplementary_result") is not None
        if not in_supplementary_loop:
            emit(on_event, {"type": "stage_start", "agent": "analyzer", "progress": 60})
            analyzer_events = on_event
        else:
            analyzer_events = wrap_agent_name(on_event, "supplementary_search")
        analysis = await self.analyzer.run(state, on_event=analyzer_events)
        state.analyses.append(analysis)
        if isinstance(analysis, dict):
            state.claim_graph = analysis.get("claims", [])
            if not in_supplementary_loop:
                state.claim_audit = []
            for claim in state.claim_graph:
                if not any(entry.get("claim_id") == claim.get("claim_id") for entry in state.claim_audit):
                    state.claim_audit.append({
                        "claim_id": claim.get("claim_id", ""),
                        "claim_text": claim.get("claim_text", ""),
                        "evidence_ids": claim.get("evidence_ids", []),
                        "analyzer_confidence": claim.get("confidence", 0.5),
                        "critic_findings": [],
                        "writer_sections_used": [],
                        "validator_status": "unverified",
                    })
        if not in_supplementary_loop:
            emit(on_event, {"type": "stage_complete", "agent": "analyzer", "progress": 65, "output": analysis})
        return context

    async def _critic(self, context: GraphContext) -> GraphContext:
        state = context["state"]
        on_event = context.get("on_event")
        in_supplementary_loop = context.get("supplementary_result") is not None
        if not in_supplementary_loop:
            state.current_stage = "critic"
            state.progress = 75
            emit(on_event, {"type": "stage_start", "agent": "critic", "progress": 75})
            critic_events = on_event
        else:
            critic_events = wrap_agent_name(on_event, "supplementary_search")
        critique = await self.critic.run(state, on_event=critic_events)
        state.critiques.append(critique)
        if isinstance(critique, dict):
            for finding in critique.get("findings", []):
                target_id = finding.get("target_id", "")
                for audit_entry in state.claim_audit:
                    if audit_entry["claim_id"] == target_id:
                        audit_entry["critic_findings"].append(finding)
        if not in_supplementary_loop:
            emit(on_event, {"type": "stage_complete", "agent": "critic", "progress": 80, "output": critique})
        else:
            context["supplementary_result"] = None
        return context

    async def _supplementary_search(self, context: GraphContext) -> GraphContext:
        state = context["state"]
        on_event = context.get("on_event")
        critique = state.critiques[-1] if state.critiques else {}
        loop_count = context.get("supplementary_loop_count", 0) + 1
        context["supplementary_loop_count"] = loop_count
        emit(on_event, {"type": "stage_start", "agent": "supplementary_search", "progress": 80 + loop_count})

        supplementary_queries: list[str] = []
        for finding in critique.get("findings", []):
            supplementary_queries.extend(finding.get("suggested_search_queries", []))

        if not supplementary_queries:
            emit(on_event, {"type": "stage_complete", "agent": "supplementary_search", "progress": 82 + loop_count})
            context["supplementary_result"] = None
            return context

        supp_sq = {
            "id": f"supp_{loop_count}",
            "question": "补充研究：" + "；".join(supplementary_queries[:3]),
            "search_queries": supplementary_queries[:3],
            "priority": 1,
        }
        supp_state = state.model_copy(deep=True)
        supp_state.plan = [supp_sq]
        searcher = self.searcher_factory()
        supp_result = await searcher.run(supp_state, on_event=wrap_agent_name(on_event, "supplementary_search"))
        state.sub_results[f"supp_{loop_count}"] = supp_result
        for source in supp_result.get("sources", []):
            url = source.get("url", "")
            if url:
                state.source_registry[url] = source
        emit(on_event, {
            "type": "stage_complete",
            "agent": "supplementary_search",
            "progress": 82 + loop_count,
            "output": supp_result,
        })
        context["supplementary_result"] = supp_result
        return context

    async def _writer(self, context: GraphContext) -> GraphContext:
        state = context["state"]
        on_event = context.get("on_event")
        state.current_stage = "writer"
        state.progress = 90
        emit(on_event, {"type": "stage_start", "agent": "writer", "progress": 90})
        report = await self.writer.run(state, on_event=on_event)
        state.final_report = report
        emit(on_event, {
            "type": "stage_complete",
            "agent": "writer",
            "progress": 92,
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
        emit(on_event, {
            "type": "stage_start",
            "agent": agent_name,
            "progress": 96,
            "repair_count": attempt,
        })
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
        emit(on_event, {
            "type": "report_update",
            "agent": "writer",
            "progress": 97,
            "output": state.final_report,
        })
        return context

    def _route_after_critic(self, context: GraphContext) -> str:
        state = context["state"]
        critique = state.critiques[-1] if state.critiques else {}
        topo_cfg = get_config().topology.get("hierarchical", {})
        max_loops = topo_cfg.get("max_research_loops", 1)
        loop_count = context.get("supplementary_loop_count", 0)
        if loop_count < max_loops and (critique.get("needs_more_research") or critique.get("overall_assessment") == "needs_research"):
            return "supplementary_search"
        return "writer"

    def _route_after_validator(self, context: GraphContext) -> str:
        state = context["state"]
        on_event = context.get("on_event")
        validation = context.get("last_validation", {})
        topo_cfg = get_config().topology.get("hierarchical", {})
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


def build_hierarchical_graph() -> HierarchicalGraphRunner:
    registry = ModelRegistry()
    key_pool = APIKeyPool()
    router = FallbackRouter(registry, key_pool)
    llm_client = LLMClient()
    return HierarchicalGraphRunner(
        planner=PlannerAgent(router=router, llm_client=llm_client, key_pool=key_pool),
        analyzer=AnalyzerAgent(router=router, llm_client=llm_client, key_pool=key_pool),
        critic=CriticAgent(router=router, llm_client=llm_client, key_pool=key_pool),
        writer=WriterAgent(router=router, llm_client=llm_client, key_pool=key_pool),
        validator=ValidatorAgent(router=router, llm_client=llm_client, key_pool=key_pool),
        searcher_factory=lambda: SearcherAgent(router=router, llm_client=llm_client, key_pool=key_pool),
        reader_factory=lambda: ReaderAgent(router=router, llm_client=llm_client, key_pool=key_pool),
    )
