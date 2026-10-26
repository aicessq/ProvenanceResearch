"""云服务配置面契约（P5 验收：加密存储/主密钥门/旧值保留/出站逐能力授权）。

覆盖：凭证加密落盘且 GET 不回显、CONFIG_ENCRYPTION_KEY 缺失/弱/格式错拒绝保存、
轮换失败不丢旧密文、校验失败保留旧值、删除覆盖恢复环境值、
provider/endpoint/model 变更使旧出站授权失效、默认拒绝外送。
"""

from __future__ import annotations

import asyncio
import base64
import json
import os

import pytest

from app.services.cloud_config_service import CloudConfigService, ConfigValidationError
from app.services.config_secrets import ConfigEncryptionError, SecretVault
from app.services.outbound_gate import OutboundGate, config_fingerprint

GOOD_KEY = base64.urlsafe_b64encode(bytes(range(32))).decode("ascii")  # 32 字节、256 个不同值中的 32 个
WEAK_KEY = base64.urlsafe_b64encode(b"\x00" * 32).decode("ascii")  # 全同字节，强度不足
OTHER_KEY = base64.urlsafe_b64encode(bytes(range(100, 132))).decode("ascii")


def make_service(tmp_path, *, env: dict | None = None) -> CloudConfigService:
    env = dict(env or {})
    env.setdefault("CONFIG_ENCRYPTION_KEY", GOOD_KEY)
    vault = SecretVault(env["CONFIG_ENCRYPTION_KEY"], persist_path=tmp_path / "secrets.json")
    return CloudConfigService(vault=vault, overrides_path=tmp_path / "overrides.json", environ=env)


# ---------------- SecretVault ----------------

def test_secret_vault_encrypts_at_rest_and_never_plaintext(tmp_path) -> None:
    vault = SecretVault(GOOD_KEY, persist_path=tmp_path / "secrets.json")
    vault.save("cloud_config:llm", "sk-super-secret")
    raw = (tmp_path / "secrets.json").read_text(encoding="utf-8")
    assert "sk-super-secret" not in raw  # 落盘只有密文
    assert vault.load("cloud_config:llm") == "sk-super-secret"


def test_secret_vault_refuses_missing_weak_or_bad_key(tmp_path) -> None:
    with pytest.raises(ConfigEncryptionError):
        SecretVault("", persist_path=tmp_path / "s.json").save("a", "secret")  # 缺失
    with pytest.raises(ConfigEncryptionError):
        SecretVault(WEAK_KEY, persist_path=tmp_path / "s.json")  # 弱密钥启动即拒
    with pytest.raises(ConfigEncryptionError):
        SecretVault("not-base64!!", persist_path=tmp_path / "s.json")  # 格式不符


def test_rotate_keeps_old_ciphertext_on_failure(tmp_path) -> None:
    vault = SecretVault(GOOD_KEY, persist_path=tmp_path / "secrets.json")
    vault.save("a", "secret-1")
    before = (tmp_path / "secrets.json").read_text(encoding="utf-8")

    with pytest.raises(ConfigEncryptionError):
        vault.rotate(WEAK_KEY)  # 新钥弱 → 失败
    assert (tmp_path / "secrets.json").read_text(encoding="utf-8") == before  # 旧密文保留

    count = vault.rotate(OTHER_KEY)  # 轮换成功
    assert count == 1
    assert vault.load("a") == "secret-1"
    rotated = SecretVault(OTHER_KEY, persist_path=tmp_path / "secrets.json")
    assert rotated.load("a") == "secret-1"  # 新钥可解


# ---------------- CloudConfigService ----------------

def test_env_resolution_override_and_restore(tmp_path) -> None:
    env = {"LLM_PROVIDER": "deepseek", "LLM_MODEL": "deepseek-chat", "LLM_API_KEY": "sk-env", "CONFIG_ENCRYPTION_KEY": GOOD_KEY}
    service = make_service(tmp_path, env=env)

    view = service.view()["capabilities"]["llm"]
    assert view == {**view, "source": "env", "provider": "deepseek", "api_key": "configured"}

    updated = service.update_capability("llm", {"model": "deepseek-reasoner", "api_key": "sk-new"})
    assert updated["source"] == "override"
    assert updated["model"] == "deepseek-reasoner"
    assert updated["api_key"] == "configured"
    assert "sk-new" not in json.dumps(updated)  # 视图不回显密钥

    removed = service.remove_override("llm")
    assert removed["source"] == "env"
    assert removed["model"] == "deepseek-chat"
    assert service.resolve("llm")["api_key"] == "sk-env"  # 恢复环境值


def test_validation_failure_keeps_old_values(tmp_path) -> None:
    env = {"LLM_PROVIDER": "deepseek", "LLM_MODEL": "deepseek-chat", "LLM_API_KEY": "sk-env", "CONFIG_ENCRYPTION_KEY": GOOD_KEY}
    service = make_service(tmp_path, env=env)
    service.update_capability("llm", {"model": "deepseek-reasoner"})

    with pytest.raises(ConfigValidationError):
        service.update_capability("llm", {"provider": "", "model": "x"})  # provider 空
    with pytest.raises(ConfigValidationError):
        service.update_capability("llm", {"unknown_field": 1})  # 未知字段
    with pytest.raises(ConfigValidationError):
        service.update_capability("llm", {"base_url": "http://api.deepseek.com"})  # http 端点拒绝

    assert service.resolve("llm")["model"] == "deepseek-reasoner"  # 旧值保持


def test_save_without_master_key_refuses(tmp_path) -> None:
    service = make_service(tmp_path, env={"LLM_PROVIDER": "deepseek", "LLM_MODEL": "m", "CONFIG_ENCRYPTION_KEY": ""})
    with pytest.raises(ConfigEncryptionError):
        service.update_capability("llm", {"api_key": "sk-x"})  # 主密钥缺失 → 拒绝保存
    assert service.resolve("llm")["api_key"] is None


def test_embedding_change_marks_index_migration(tmp_path) -> None:
    service = make_service(tmp_path, env={"EMBEDDING_PROVIDER": "openai", "EMBEDDING_MODEL": "text-embedding-3"})
    view = service.update_capability("embedding", {"model": "text-embedding-3-large"})
    assert view["index_migration_pending"] is True  # 切换须索引迁移（P3a 契约）


# ---------------- OutboundGate ----------------

def test_outbound_gate_default_deny_and_stale_approvals() -> None:
    gate = OutboundGate(upload_allowed=False)
    ok, reason = gate.check("llm", provider="deepseek", endpoint="https://api.deepseek.com", model="m")
    assert not ok and reason == "cloud_upload_not_authorized"

    gate = OutboundGate(upload_allowed=True)
    fp = gate.approve("llm", "deepseek", "https://api.deepseek.com", "m")
    ok, reason = gate.check("llm", provider="deepseek", endpoint="https://api.deepseek.com", model="m")
    assert ok and reason == "approved"

    # provider/endpoint/model 任一变更 → 旧授权失效
    ok, reason = gate.check("llm", provider="deepseek", endpoint="https://api.deepseek.com", model="m-turbo")
    assert not ok and reason == "approval_stale_config_changed"

    ok, reason = gate.check("ocr", provider="deepseek", endpoint="https://api.deepseek.com", model="m")
    assert not ok and reason == "capability_not_approved"  # 逐能力授权

    assert config_fingerprint("llm", "deepseek", "https://api.deepseek.com/", "m") == fp  # 规范化 endpoint


def test_approve_outbound_persists_runtime_approval(tmp_path) -> None:
    env = {"LLM_PROVIDER": "deepseek", "LLM_MODEL": "m", "LLM_BASE_URL": "https://api.deepseek.com", "CONFIG_ENCRYPTION_KEY": GOOD_KEY}
    service = make_service(tmp_path, env=env)
    assert service.check_outbound("llm") == (False, "cloud_upload_not_authorized")

    service._gate.upload_allowed = True  # 用户在 env 打开总开关（启动参数）
    approved = service.approve_outbound("llm")
    assert approved["approved"] is True
    assert service.check_outbound("llm") == (True, "approved")

    # 重新加载服务（读持久化授权）
    reopened = CloudConfigService(
        vault=SecretVault(GOOD_KEY, persist_path=tmp_path / "secrets.json"),
        overrides_path=tmp_path / "overrides.json",
        environ=env,
    )
    reopened._gate.upload_allowed = True
    assert reopened.check_outbound("llm") == (True, "approved")


def test_source_outbound_rows_and_approve(tmp_path) -> None:
    service = make_service(tmp_path, env={"CONFIG_ENCRYPTION_KEY": GOOD_KEY})
    service._gate.upload_allowed = True
    view = service.outbound_view()["capabilities"]
    assert "search:web" in view and "search:arxiv" in view  # 搜索来源外送查询也在授权面
    assert view["search:web"]["approved"] is False

    approved = service.approve_outbound("search:web")
    assert approved["approved"] is True
    assert service.check_outbound("search:web") == (True, "approved")
    assert service.check_outbound("search:arxiv") == (False, "capability_not_approved")  # 逐能力独立


def test_runtime_build_enforces_outbound_gate(monkeypatch, tmp_path) -> None:
    """凭证不等于授权：出站门未开/未授权时生产运行时显式拒绝构建。"""
    import json as _json

    from app.services.agentic_service import AgenticConfigError, build_cloud_runtime
    from app.services.outbound_gate import OutboundGate

    monkeypatch.setenv("CLOUD_CONFIG_OVERRIDES_PATH", str(tmp_path / "overrides.json"))
    monkeypatch.setenv("CLOUD_SECRETS_PATH", str(tmp_path / "secrets.json"))
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("LLM_MODEL", "deepseek-chat")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    monkeypatch.delenv("CLOUD_DATA_UPLOAD_ALLOWED", raising=False)

    with pytest.raises(AgenticConfigError) as exc:
        build_cloud_runtime()
    assert exc.value.code == "cloud_upload_not_authorized"  # 默认拒绝

    monkeypatch.setenv("CLOUD_DATA_UPLOAD_ALLOWED", "true")
    gate = OutboundGate.from_env()
    approvals = {
        "llm": gate.expected_fingerprint("llm", "deepseek", "unset", "deepseek-chat"),
        "search:web": gate.expected_fingerprint("search:web", "tavily", "https://api.tavily.com", ""),
        "search:arxiv": gate.expected_fingerprint("search:arxiv", "arxiv", "https://export.arxiv.org", ""),
    }
    monkeypatch.setenv("CLOUD_DATA_APPROVALS_JSON", _json.dumps(approvals))
    runtime = build_cloud_runtime()  # 授权齐备才放行
    assert runtime.llm is not None
    assert set(runtime.executor.tool_names) >= {"kb_search", "web_search", "arxiv_search"}


def test_local_embedding_configuration_does_not_require_cloud_key(tmp_path):
    model_dir = tmp_path / "bge-base-en-v1.5"
    model_dir.mkdir()
    env = {"EMBEDDING_PROVIDER": "local", "EMBEDDING_MODEL": "BAAI/bge-base-en-v1.5",
           "EMBEDDING_MODEL_PATH": str(model_dir)}
    service = make_service(tmp_path, env=env)
    assert service.view()["capabilities"]["embedding"]["configured"] is True
    assert service.view()["capabilities"]["embedding"]["api_key"] == "missing"
    assert service.check_outbound("embedding")[0] is False
    missing_env = {**env, "EMBEDDING_MODEL_PATH": str(tmp_path / "absent")}
    assert make_service(tmp_path, env=missing_env).view()["capabilities"]["embedding"]["configured"] is False
    env["VISION_PROVIDER"] = "local"
    env["VISION_MODEL"] = "forbidden-local-vision"
    assert make_service(tmp_path, env=env).view()["capabilities"]["vision"]["configured"] is False
