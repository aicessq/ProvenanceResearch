"""云出站逐能力授权门（design.md §9）。

- `CLOUD_DATA_UPLOAD_ALLOWED=false` 为总开关：拒绝所有会外送用户问题/证据/文件的
  第三方调用（模型、搜索、fetch、OCR/vision），报 cloud_upload_not_authorized。
- 总开关开启仍需**逐能力授权**：`CLOUD_DATA_APPROVALS_JSON` 映射能力 ID → 用户
  审核过的配置指纹。指纹 = 能力+provider+规范 endpoint+model/version 的哈希，
  **不含 API key**；provider/endpoint/model/地域变更使旧授权失效（指纹不匹配）。
- 凭证不等于授权：健康检查/配置验证也只能按明确授权范围发送数据。
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field


def config_fingerprint(capability: str, provider: str, endpoint: str, model: str = "", region: str = "") -> str:
    """配置指纹：能力+provider+规范 endpoint+model/region。不含 API key。"""
    material = "|".join(
        [
            capability.strip(),
            provider.strip().lower(),
            (endpoint or "").strip().rstrip("/").lower(),
            (model or "").strip(),
            (region or "").strip(),
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass
class OutboundGate:
    upload_allowed: bool = False
    approvals: dict[str, str] = field(default_factory=dict)
    region: str = ""

    @classmethod
    def from_env(cls, environ: dict | None = None) -> "OutboundGate":
        env = environ if environ is not None else os.environ
        raw_approvals = (env.get("CLOUD_DATA_APPROVALS_JSON") or "{}").strip()
        try:
            approvals = json.loads(raw_approvals) if raw_approvals else {}
        except json.JSONDecodeError:
            approvals = {}
        if not isinstance(approvals, dict):
            approvals = {}
        return cls(
            upload_allowed=(env.get("CLOUD_DATA_UPLOAD_ALLOWED") or "false").strip().lower() == "true",
            approvals={str(k): str(v) for k, v in approvals.items()},
            region=(env.get("CLOUD_DATA_REGION") or "").strip(),
        )

    def expected_fingerprint(self, capability: str, provider: str, endpoint: str, model: str = "") -> str:
        return config_fingerprint(capability, provider, endpoint, model, self.region)

    def check(self, capability: str, *, provider: str, endpoint: str, model: str = "") -> tuple[bool, str]:
        """返回 (allowed, reason)。reason 供 problem+json/提示展示（脱敏）。"""
        if not self.upload_allowed:
            return False, "cloud_upload_not_authorized"
        expected = self.expected_fingerprint(capability, provider, endpoint, model)
        approved = self.approvals.get(capability)
        if not approved:
            return False, "capability_not_approved"
        if approved != expected:
            return False, "approval_stale_config_changed"
        return True, "approved"

    def approve(self, capability: str, provider: str, endpoint: str, model: str = "") -> str:
        """登记当前配置指纹为该能力授权；返回指纹。"""
        fingerprint = self.expected_fingerprint(capability, provider, endpoint, model)
        self.approvals[capability] = fingerprint
        return fingerprint

    def to_view(self) -> dict:
        return {
            "upload_allowed": self.upload_allowed,
            "region": self.region,
            "approvals": dict(self.approvals),
        }
