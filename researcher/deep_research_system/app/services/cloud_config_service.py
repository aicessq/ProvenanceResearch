"""云服务配置（design.md §9 / P5）：env 启动参数 + 前端可改运行时覆盖。

- 五个模型能力（llm/embedding/reranker/ocr/vision）+ 搜索来源 key（tavily）。
  env 形如 `{CAP}_PROVIDER/_MODEL/_MODEL_VERSION/_API_KEY/_BASE_URL`（.env.example 契约）。
- 运行时覆盖存 `data/cloud_config_overrides.json`（非密文）；**api_key 只进 SecretVault
  密文**，GET/日志/trace 永不回显（视图里只回 configured/missing）。
- 校验失败保留旧值（先验后写）；删除覆盖即恢复环境值。
- 能力/凭证与出站授权分开：凭证不等于授权（outbound_gate 逐能力指纹）。
- embedding 变更打 `index_migration_pending` 标记（切换必须索引迁移，P3a 契约；
  迁移执行器随 KE 接入——标记对 UI 可见，未迁移不得当作新索引已生效）。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.model_pool.endpoint_guard import validate_model_endpoint
from app.services.config_secrets import ConfigEncryptionError, SecretVault
from app.services.outbound_gate import OutboundGate

logger = get_logger(__name__)

CAPABILITIES: dict[str, str] = {
    "llm": "LLM",
    "embedding": "EMBEDDING",
    "reranker": "RERANKER",
    "ocr": "OCR",
    "vision": "VISION",
}
SOURCE_KEYS = ("tavily",)
SECRET_NAME_PREFIX = "cloud_config:"

# 搜索来源的出站授权预置（能力 ID → provider/固定端点；模型为空）
SOURCE_OUTBOUND: dict[str, tuple[str, str, str, str]] = {
    "search:web": ("search:web", "tavily", "https://api.tavily.com", ""),
    "search:arxiv": ("search:arxiv", "arxiv", "https://export.arxiv.org", ""),
}


class ConfigValidationError(Exception):
    """配置非法（端点不允许/字段缺失等）：调用方映射 problem+json，旧值保持不变。"""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class CloudConfigService:
    def __init__(
        self,
        *,
        vault: SecretVault | None = None,
        overrides_path: str | Path | None = None,
        environ: dict | None = None,
    ) -> None:
        self._env = environ if environ is not None else dict(os.environ)
        self._vault = vault if vault is not None else SecretVault(self._env.get("CONFIG_ENCRYPTION_KEY"))
        self._overrides_path = Path(
            overrides_path
            or os.environ.get("CLOUD_CONFIG_OVERRIDES_PATH")
            or Path(__file__).resolve().parents[2] / "data" / "cloud_config_overrides.json"
        )
        self._gate = OutboundGate.from_env(self._env)
        runtime = self._read_overrides().get("outbound_approvals") or {}
        self._gate.approvals.update({str(k): str(v) for k, v in runtime.items()})

    # ---------- 存储 ----------

    def _read_overrides(self) -> dict:
        if not self._overrides_path.exists():
            return {}
        try:
            return json.loads(self._overrides_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ConfigValidationError("overrides_corrupted", f"覆盖配置文件损坏: {type(exc).__name__}") from exc

    def _write_overrides(self, store: dict) -> None:
        self._overrides_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._overrides_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._overrides_path)

    # ---------- 解析与视图 ----------

    def resolve(self, capability: str) -> dict[str, Any]:
        """生效配置（内部用，含 api_key 明文）：env 为底、运行时覆盖优先。"""
        if capability not in CAPABILITIES:
            raise ConfigValidationError("unknown_capability", f"未知能力: {capability}")
        prefix = CAPABILITIES[capability]
        env_vals = {
            "provider": (self._env.get(f"{prefix}_PROVIDER") or "").strip(),
            "model": (self._env.get(f"{prefix}_MODEL") or "").strip(),
            "model_version": (self._env.get(f"{prefix}_MODEL_VERSION") or "").strip(),
            "base_url": (self._env.get(f"{prefix}_BASE_URL") or "").strip(),
        }
        override = dict(self._read_overrides().get(capability) or {})
        # 空覆盖值视为未覆盖（回退环境值）：显式清空即"恢复该项的环境配置"
        merged = {**env_vals, **{k: v for k, v in override.items() if k in env_vals and v}}
        secret_name = SECRET_NAME_PREFIX + capability
        api_key = self._vault.load(secret_name) if self._vault.enabled else None
        if api_key is None:
            api_key = (self._env.get(f"{prefix}_API_KEY") or "").strip() or None
        merged["api_key"] = api_key
        merged["source"] = "override" if override else "env"
        merged["index_migration_pending"] = bool(override.get("index_migration_pending"))
        return merged

    def _mask(self, capability: str) -> dict[str, Any]:
        cfg = self.resolve(capability)
        local_embedding = (
            capability == "embedding" and cfg["provider"] == "local"
            and bool(cfg["model"])
            and bool(self._env.get("EMBEDDING_MODEL_PATH"))
            and Path(self._env["EMBEDDING_MODEL_PATH"]).is_dir()
        )
        return {
            "configured": local_embedding or bool(cfg["provider"] and cfg["api_key"]),
            "source": cfg["source"],
            "provider": cfg["provider"],
            "model": cfg["model"],
            "model_version": cfg["model_version"],
            "base_url": cfg["base_url"],
            "api_key": "configured" if cfg["api_key"] else "missing",
            "index_migration_pending": cfg["index_migration_pending"],
        }

    def view(self) -> dict[str, Any]:
        sources = {
            name: {"configured": bool((self._env.get("TAVILY_API_KEY") or "").strip()), "source": "env"}
            for name in SOURCE_KEYS
        }
        return {
            "capabilities": {cap: self._mask(cap) for cap in CAPABILITIES},
            "sources": sources,
            "vault_enabled": self._vault.enabled,
            "outbound": self.outbound_view(),
        }

    def outbound_view(self) -> dict[str, Any]:
        caps: dict[str, Any] = {}
        for cap in list(CAPABILITIES) + list(SOURCE_OUTBOUND):
            if cap in SOURCE_OUTBOUND:
                _, provider, endpoint, model = SOURCE_OUTBOUND[cap]
            else:
                cfg = self.resolve(cap)
                provider = cfg["provider"] or "unset"
                endpoint = cfg["base_url"] or "unset"
                model = cfg["model"]
            fingerprint = self._gate.expected_fingerprint(cap, provider, endpoint, model)
            allowed, reason = self._gate.check(cap, provider=provider, endpoint=endpoint, model=model)
            caps[cap] = {
                "fingerprint": fingerprint,
                "approved": allowed,
                "reason": reason,
                "provider": provider,
                "endpoint": endpoint,
                "model": model,
            }
        return {**self._gate.to_view(), "capabilities": caps}

    # ---------- 写入（先验后写，失败保留旧值） ----------

    def update_capability(self, capability: str, payload: dict[str, Any]) -> dict[str, Any]:
        if capability not in CAPABILITIES:
            raise ConfigValidationError("unknown_capability", f"未知能力: {capability}")
        unknown = set(payload) - {"provider", "model", "model_version", "base_url", "api_key"}
        if unknown:
            raise ConfigValidationError("invalid_params", f"未知字段: {sorted(unknown)}")

        previous = self.resolve(capability)

        def pick(field: str) -> str:
            if field in payload and not str(payload.get(field) or "").strip():
                raise ConfigValidationError("invalid_params", f"{field} 显式为空：如需恢复环境值请删除该覆盖")
            return (payload.get(field) or previous[field]).strip()

        provider = pick("provider")
        model = pick("model")
        model_version = (payload.get("model_version") or previous["model_version"]).strip()
        base_url = (payload.get("base_url") or previous["base_url"]).strip()

        if not provider:
            raise ConfigValidationError("invalid_params", "provider 不能为空")
        if not model:
            raise ConfigValidationError("invalid_params", "model 不能为空")
        if base_url:
            try:
                base_url = validate_model_endpoint(provider, base_url)
            except Exception as exc:
                raise ConfigValidationError("endpoint_not_allowed", f"端点不允许或非法: {exc}") from exc

        api_key = payload.get("api_key")
        if api_key is not None:
            # 主密钥缺失/弱/格式不符 → ConfigEncryptionError，旧值保持不变
            self._vault.save(SECRET_NAME_PREFIX + capability, str(api_key))

        store = self._read_overrides()
        record: dict[str, Any] = {
            "provider": provider,
            "model": model,
            "model_version": model_version,
            "base_url": base_url,
            "updated_at": _now_iso(),
        }
        if capability == "embedding":
            identity_changed = (provider, model, base_url) != (previous["provider"], previous["model"], previous["base_url"])
            record["index_migration_pending"] = identity_changed or bool(previous.get("index_migration_pending"))
        store[capability] = record
        self._write_overrides(store)
        logger.info(f"云配置覆盖已更新: {capability}（source=override）")
        return self._mask(capability)

    def remove_override(self, capability: str) -> dict[str, Any]:
        if capability not in CAPABILITIES:
            raise ConfigValidationError("unknown_capability", f"未知能力: {capability}")
        store = self._read_overrides()
        store.pop(capability, None)
        self._write_overrides(store)
        self._vault.delete(SECRET_NAME_PREFIX + capability)
        logger.info(f"云配置覆盖已删除，恢复环境值: {capability}")
        return self._mask(capability)

    def rotate_master_key(self, new_master_key_raw: str) -> int:
        try:
            return self._vault.rotate(new_master_key_raw)
        except ConfigEncryptionError:
            raise

    # ---------- 出站授权 ----------

    def approve_outbound(self, capability: str) -> dict[str, Any]:
        if capability in SOURCE_OUTBOUND:
            _, provider, endpoint, model = SOURCE_OUTBOUND[capability]
        elif capability in CAPABILITIES:
            cfg = self.resolve(capability)
            provider = cfg["provider"]
            endpoint = cfg["base_url"] or "unset"
            model = cfg["model"]
            if not provider:
                raise ConfigValidationError("invalid_params", f"{capability} 未配置 provider，无法计算授权指纹")
        else:
            raise ConfigValidationError("unknown_capability", f"未知能力: {capability}")
        fingerprint = self._gate.approve(capability, provider, endpoint, model)
        store = self._read_overrides()
        approvals = store.get("outbound_approvals") or {}
        approvals[capability] = fingerprint
        store["outbound_approvals"] = approvals
        self._write_overrides(store)
        logger.info(f"出站授权已登记: {capability} -> {fingerprint[:12]}…")
        return self.outbound_view()["capabilities"][capability]

    def check_outbound(self, capability: str) -> tuple[bool, str]:
        if capability in SOURCE_OUTBOUND:
            _, provider, endpoint, model = SOURCE_OUTBOUND[capability]
            return self._gate.check(capability, provider=provider, endpoint=endpoint, model=model)
        cfg = self.resolve(capability)
        return self._gate.check(capability, provider=cfg["provider"] or "unset", endpoint=cfg["base_url"] or "unset", model=cfg["model"])
