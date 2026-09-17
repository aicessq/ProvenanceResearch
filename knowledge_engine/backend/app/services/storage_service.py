"""本地文件存储服务。

Phase 2 第一版固定使用本地文件系统保存原始上传文件，
并保证路径稳定、可回溯、不会覆盖旧版本。
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from app.config import get_settings

settings = get_settings()

_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


class StorageError(RuntimeError):
    """文件存储失败时抛出的异常。"""


class LocalStorageService:
    """本地原始文件存储服务。"""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or settings.storage_root)

    def ensure_storage_root(self) -> Path:
        """确保 storage 根目录存在。"""
        self.root.mkdir(parents=True, exist_ok=True)
        return self.root

    def sanitize_filename(self, filename: str) -> str:
        """做最小文件名清洗，避免路径穿越与奇怪字符。"""
        original = Path(filename).name.strip() or "upload.bin"
        sanitized = _SAFE_FILENAME_RE.sub("_", original)
        return sanitized or "upload.bin"

    def build_document_storage_path(
        self,
        *,
        document_id: uuid.UUID,
        version_id: uuid.UUID,
        original_filename: str,
    ) -> Path:
        """生成稳定、可回溯的原始文件存储路径。"""
        safe_filename = self.sanitize_filename(original_filename)
        return self.ensure_storage_root() / "documents" / str(document_id) / str(version_id) / safe_filename

    def save_file(
        self,
        *,
        document_id: uuid.UUID,
        version_id: uuid.UUID,
        original_filename: str,
        file_bytes: bytes,
    ) -> Path:
        """保存原始文件并返回实际落盘路径。"""
        target_path = self.build_document_storage_path(
            document_id=document_id,
            version_id=version_id,
            original_filename=original_filename,
        )
        target_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            target_path.write_bytes(file_bytes)
        except OSError as exc:  # pragma: no cover - 依赖真实文件系统异常
            raise StorageError(f"保存原始文件失败：{exc}") from exc
        return target_path

    def delete_file(self, path: str | Path) -> None:
        """删除已保存文件；用于数据库失败时尽量清理。"""
        target = Path(path)
        try:
            if target.exists():
                target.unlink()
        except OSError:
            # 清理失败不再二次抛错，交由调用方记录日志即可。
            return
