"""Hash 工具（file_hash / chunk_hash）。

- Phase 2：文件级哈希 `file_hash`
- Phase 4：chunk 级哈希 `chunk_hash`

chunk_hash 需要基于 `normalized_text` 计算，
对无意义空白变化不敏感，但对真实语义变化敏感。
"""

from __future__ import annotations

import hashlib
import re


def calculate_file_hash(file_bytes: bytes) -> str:
    """基于原始文件 bytes 计算 SHA-256。"""
    return hashlib.sha256(file_bytes).hexdigest()


def normalize_chunk_text(text: str) -> str:
    """规范化 chunk 文本，减少无意义空白对 hash 的影响。"""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    lines = [line.strip() for line in normalized.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def calculate_chunk_hash(normalized_text: str) -> str:
    """基于 normalized_text 计算稳定的 chunk_hash。"""
    return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
