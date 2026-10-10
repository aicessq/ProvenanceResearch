"""P2.5-0.3 key/端点严格绑定测试（provider → capability → key pool）。"""

from __future__ import annotations

import pytest

from app.core.config import get_config
from app.core.errors import ProviderUnavailableError
from app.model_pool.client import LLMClient
from app.model_pool.key_pool import APIKeyPool
from app.model_pool.registry import ModelRegistry
from app.model_pool.router import _has_api_key
from app.schemas.model import ModelSpec


def _clear_key_env(monkeypatch, *env_names: str) -> None:
    for name in env_names:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.setattr(get_config().settings, name, None)


def test_get_api_key_returns_none_instead_of_foreign_slot_key(monkeypatch) -> None:
    """没有自身绑定 key 时返回 None，禁止回退到其他 slot 的 MODEL_*_API_KEY。"""
    _clear_key_env(monkeypatch, "DEEPSEEK_API_KEY")
    monkeypatch.setenv("MODEL_SEARCH_API_KEY", "foreign-slot-key")
    monkeypatch.setenv("MODEL_WRITING_API_KEY", "another-slot-key")

    pool = APIKeyPool()
    assert pool.get_api_key("deepseek-chat") is None


def test_get_api_key_uses_own_bound_key(monkeypatch) -> None:
    _clear_key_env(monkeypatch, "DEEPSEEK_API_KEY")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "own-key")
    monkeypatch.setenv("MODEL_SEARCH_API_KEY", "foreign-slot-key")

    pool = APIKeyPool()
    assert pool.get_api_key("deepseek-chat") == "own-key"


def test_has_api_key_ignores_foreign_slot_key(monkeypatch) -> None:
    registry = ModelRegistry()
    model = registry.get("deepseek-chat")
    assert model is not None

    _clear_key_env(monkeypatch, "DEEPSEEK_API_KEY")
    monkeypatch.setenv("MODEL_SEARCH_API_KEY", "foreign-slot-key")
    assert _has_api_key(model) is False

    monkeypatch.setenv("DEEPSEEK_API_KEY", "own-key")
    assert _has_api_key(model) is True


def test_resolve_base_url_never_grabs_other_slot_base(monkeypatch) -> None:
    """端点严格绑定：自身 api_base 缺失时只用 provider 官方默认，不取其他 slot 的 base。"""
    monkeypatch.setenv("MODEL_SEARCH_API_BASE", "https://other-slot.example.com/v1")
    client = LLMClient()
    model = ModelSpec(
        name="deepseek-chat",
        provider="deepseek",
        api_base=None,
        capabilities=[],
        cost_tier="low",
        latency_tier="fast",
    )
    base = client._resolve_base_url(model)
    assert base.startswith("https://api.deepseek.com")
    assert "other-slot.example.com" not in base


def test_resolve_base_url_prefers_own_binding(monkeypatch) -> None:
    monkeypatch.setenv("MODEL_SEARCH_API_BASE", "https://other-slot.example.com/v1")
    client = LLMClient()
    model = ModelSpec(
        name="deepseek-chat",
        provider="deepseek",
        api_base="https://api.deepseek.com/v1/",
        capabilities=[],
        cost_tier="low",
        latency_tier="fast",
    )
    assert client._resolve_base_url(model) == "https://api.deepseek.com/v1"


def test_resolve_base_url_raises_when_no_binding(monkeypatch) -> None:
    monkeypatch.setattr(get_config().settings, "DEEPSEEK_API_BASE", "")
    client = LLMClient()
    model = ModelSpec(
        name="deepseek-chat",
        provider="deepseek",
        api_base="",
        capabilities=[],
        cost_tier="low",
        latency_tier="fast",
    )
    with pytest.raises(ProviderUnavailableError):
        client._resolve_base_url(model)
