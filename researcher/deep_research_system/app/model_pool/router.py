from __future__ import annotations

import logging
import os

from app.core.config import get_config
from app.model_pool.key_pool import APIKeyPool
from app.model_pool.registry import ModelRegistry
from app.schemas.model import ModelSpec
from app.schemas.task import TaskRequirement

logger = logging.getLogger(__name__)

COST_RANK = {"low": 0, "mid": 1, "high": 2}
LATENCY_RANK = {"fast": 0, "medium": 1, "slow": 2}


def _has_api_key(model: ModelSpec) -> bool:
    """Check if THIS model's own bound key is available (P2.5-0.3 严格绑定)。

    只认 models.yaml 为该模型登记的 key env；其他 slot/provider 的 key
    不能让本模型显得"可用"。
    """
    config = get_config()
    for entry in config.get_effective_api_keys().get(model.name, []):
        env_name = entry["env_name"]
        if os.getenv(env_name, "") or getattr(config.settings, env_name, ""):
            return True
    return False


class BaseRouter:
    def __init__(self, registry: ModelRegistry) -> None:
        self.registry = registry

    async def select_model(self, requirement: TaskRequirement) -> ModelSpec | None:
        raise NotImplementedError

    def _filter_available(self, models: list[ModelSpec]) -> list[ModelSpec]:
        available = [m for m in models if _has_api_key(m)]
        return available or models  # fallback to all if none have keys


class CapabilityRouter(BaseRouter):
    async def select_model(self, requirement: TaskRequirement) -> ModelSpec | None:
        candidates = self.registry.filter_by_capabilities(requirement.required_capabilities)
        if not candidates:
            logger.warning(f"No model satisfies capabilities: {requirement.required_capabilities}")
            candidates = self.registry.list_enabled()
        candidates = self._filter_available(candidates)
        return candidates[0] if candidates else None


class CostAwareRouter(BaseRouter):
    async def select_model(self, requirement: TaskRequirement) -> ModelSpec | None:
        candidates = self.registry.filter_by_capabilities(requirement.required_capabilities)
        if not candidates:
            candidates = self.registry.list_enabled()
        candidates = self._filter_available(candidates)
        if not candidates:
            return None
        preferred = [m for m in candidates if m.cost_tier == requirement.preferred_cost_tier]
        if preferred:
            return min(preferred, key=lambda m: LATENCY_RANK.get(m.latency_tier, 1))
        return min(candidates, key=lambda m: COST_RANK.get(m.cost_tier, 1))


class LatencyRouter(BaseRouter):
    async def select_model(self, requirement: TaskRequirement) -> ModelSpec | None:
        candidates = self.registry.filter_by_capabilities(requirement.required_capabilities)
        if not candidates:
            candidates = self.registry.list_enabled()
        candidates = self._filter_available(candidates)
        if not candidates:
            return None
        return min(candidates, key=lambda m: LATENCY_RANK.get(m.latency_tier, 1))


class SlotRouter(BaseRouter):
    """优先根据 .env 的 MODEL_{SLOT}_NAME 直接查找模型。"""

    async def select_model(self, requirement: TaskRequirement) -> ModelSpec | None:
        if not requirement.model_slot:
            return None
        return self.registry.get_by_env_slot(requirement.model_slot)


class FallbackRouter(BaseRouter):
    def __init__(self, registry: ModelRegistry, key_pool: APIKeyPool | None = None) -> None:
        super().__init__(registry)
        self.key_pool = key_pool
        self._chain: list[BaseRouter] = [
            SlotRouter(registry),
            CostAwareRouter(registry),
            CapabilityRouter(registry),
            LatencyRouter(registry),
        ]

    async def select_model(self, requirement: TaskRequirement) -> ModelSpec | None:
        for router in self._chain:
            model = await router.select_model(requirement)
            if model:
                return model
        return None
