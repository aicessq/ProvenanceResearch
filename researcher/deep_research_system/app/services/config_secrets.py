"""凭证加密存储（design.md §9）。

- 主密钥来自启动环境 `CONFIG_ENCRYPTION_KEY`（urlsafe-base64 32 字节）；
  缺失/格式不符/强度不足 → 拒绝保存凭证与启用该能力，**不回退明文或临时密钥**。
- 凭证只以 Fernet 密文落盘（`data/cloud_secrets.json`）；GET/日志/trace 永不回显。
- 主密钥轮换：全量解密旧→加密新→**验证可解后才原子替换**；失败保留旧密文。
"""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.core.logging import get_logger

logger = get_logger(__name__)

MIN_UNIQUE_KEY_BYTES = 16  # 32 字节主密钥中至少 16 个不同字节（弱密钥拒绝线）


class ConfigEncryptionError(Exception):
    """主密钥缺失/格式错误/强度不足，或密文不可解——拒绝操作而不是降级明文。"""


def _derive_fernet(master_key_raw: str) -> Fernet:
    raw = (master_key_raw or "").strip()
    if not raw:
        raise ConfigEncryptionError("CONFIG_ENCRYPTION_KEY 缺失；拒绝保存凭证（不回退明文）")
    try:
        decoded = base64.urlsafe_b64decode(raw.encode("ascii"))
    except Exception as exc:
        raise ConfigEncryptionError(f"CONFIG_ENCRYPTION_KEY 格式不符（需 urlsafe-base64 32 字节）: {type(exc).__name__}") from exc
    if len(decoded) != 32:
        raise ConfigEncryptionError(f"CONFIG_ENCRYPTION_KEY 长度非法：解码后 {len(decoded)} 字节（需 32）")
    if len(set(decoded)) < MIN_UNIQUE_KEY_BYTES:
        raise ConfigEncryptionError("CONFIG_ENCRYPTION_KEY 强度不足（不同字节数过少）；拒绝使用弱主密钥")
    return Fernet(raw.encode("ascii"))


class SecretVault:
    """加密凭证库：save/load/delete/rotate。文件落盘的是 Fernet 密文。"""

    def __init__(self, master_key_raw: str | None = None, *, persist_path: str | Path | None = None) -> None:
        self._master_key_raw = (master_key_raw if master_key_raw is not None else os.environ.get("CONFIG_ENCRYPTION_KEY")) or ""
        self._path = Path(
            persist_path
            or os.environ.get("CLOUD_SECRETS_PATH")
            or Path(__file__).resolve().parents[2] / "data" / "cloud_secrets.json"
        )
        self._fernet: Fernet | None = None
        if self._master_key_raw.strip():
            # 启动即校验：格式/强度不符直接抛错（"拒绝启动该能力"），不落明文
            self._fernet = _derive_fernet(self._master_key_raw)

    @property
    def enabled(self) -> bool:
        return self._fernet is not None

    def _require_fernet(self) -> Fernet:
        if self._fernet is None:
            raise ConfigEncryptionError("CONFIG_ENCRYPTION_KEY 缺失；拒绝保存凭证（不回退明文）")
        return self._fernet

    def _read_store(self) -> dict:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ConfigEncryptionError(f"凭证库文件损坏: {type(exc).__name__}") from exc

    def _write_store(self, store: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    def save(self, name: str, secret: str) -> None:
        fernet = self._require_fernet()
        if not secret:
            raise ConfigEncryptionError("凭证为空，拒绝保存")
        store = self._read_store()
        store[name] = {
            "token": fernet.encrypt(secret.encode("utf-8")).decode("ascii"),
            "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        self._write_store(store)

    def load(self, name: str) -> str | None:
        item = self._read_store().get(name)
        if not item:
            return None
        fernet = self._require_fernet()
        try:
            return fernet.decrypt(item["token"].encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise ConfigEncryptionError("凭证密文不可解（主密钥不匹配？）；拒绝回退明文") from exc

    def delete(self, name: str) -> bool:
        store = self._read_store()
        if name not in store:
            return False
        del store[name]
        self._write_store(store)
        return True

    def names(self) -> list[str]:
        return sorted(self._read_store().keys())

    def rotate(self, new_master_key_raw: str) -> int:
        """主密钥轮换：全部密文先用旧钥解出、用新钥加密并**验证可解**，再原子替换。

        任何一步失败都保留旧密文（不丢旧密文），抛 ConfigEncryptionError。
        """
        old_fernet = self._require_fernet()
        new_fernet = _derive_fernet(new_master_key_raw)
        store = self._read_store()
        rotated: dict[str, dict] = {}
        for name, item in store.items():
            try:
                plaintext = old_fernet.decrypt(item["token"].encode("ascii")).decode("utf-8")
                token = new_fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")
                # 验证新密文可解后才接受
                if new_fernet.decrypt(token.encode("ascii")).decode("utf-8") != plaintext:
                    raise ConfigEncryptionError(f"轮换验证失败: {name}")
                rotated[name] = {"token": token, "updated_at": item.get("updated_at", "")}
            except ConfigEncryptionError:
                raise
            except Exception as exc:
                raise ConfigEncryptionError(f"轮换失败（保留旧密文）: {name} - {type(exc).__name__}") from exc
        self._write_store(rotated)
        self._fernet = new_fernet
        self._master_key_raw = new_master_key_raw.strip()
        logger.info(f"凭证库主密钥轮换完成，共 {len(rotated)} 条")
        return len(rotated)
