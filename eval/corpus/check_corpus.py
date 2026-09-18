#!/usr/bin/env python3
"""校验 eval/corpus/manifest.jsonl 与磁盘资产的一致性。

检查项：
1. manifest schema：字段齐全、类型正确、doc_id 唯一；
2. sha256：文件存在时逐字节校验，与 manifest 不符即失败；
3. 页数：页级镜像存在时，行数须等于 manifest 的 pages；
4. 文本层声明：`text_layer_ok=false` 的条目，其镜像空页比例须 >= 0.5（防止"扫描件"标记被误改）；
5. **入库一致性（合规防线）**：`in_repo=true` 的文件必须未被 gitignore（否则不会随仓库发布）；
   `redistributable=false` / `in_repo=false` 的文件必须被 gitignore
   （否则不可再分发内容会被推送到公开仓库）；
6. 缺失处理：仓库外文件（in_repo=false）允许在本地缺失，但存在时必须通过 sha256。

退出码：0 全部通过；1 存在失败项。
纯离线脚本：不联网、不落盘、只用标准库；需要 git 才能做忽略状态检查（缺失时该项跳过并告警）。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
MANIFEST = HERE / "manifest.jsonl"
TEXT_DIR = HERE / "text"

REQUIRED_FIELDS = {
    "doc_id": str,
    "title": str,
    "lang": str,
    "category": str,
    "source_url": str,
    "retrieved_at": str,
    "filename": str,
    "pages": int,
    "sha256": str,
    "redistributable": bool,
    "in_repo": bool,
    "text_layer_ok": bool,
    "blank_page_ratio": (int, float),
    "notes": str,
}
SCAN_BLANK_THRESHOLD = 0.5  # text_layer_ok=false 的条目空页比例下限


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def is_ignored(rel_path: str) -> bool | None:
    """返回 True/False 表示忽略状态；git 不可用时返回 None。"""
    try:
        result = subprocess.run(
            ["git", "check-ignore", "-q", rel_path],
            cwd=REPO,
            capture_output=True,
        )
    except OSError:
        return None
    if result.returncode not in (0, 1):
        return None
    return result.returncode == 0


def main() -> int:
    failures: list[str] = []
    warnings: list[str] = []

    if not MANIFEST.exists():
        print(f"FAIL 找不到 manifest: {MANIFEST}")
        return 1

    rows = []
    for lineno, line in enumerate(MANIFEST.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            failures.append(f"manifest 第 {lineno} 行 JSON 解析失败: {exc}")
    print(f"manifest 条目: {len(rows)}")

    seen: set[str] = set()
    in_repo_count = 0
    git_available = True

    for row in rows:
        doc_id = row.get("doc_id", f"<no-id@{len(seen)}>")
        # 1. schema
        for field, expected_type in REQUIRED_FIELDS.items():
            if field not in row:
                failures.append(f"{doc_id}: 缺少字段 {field}")
            elif not isinstance(row[field], expected_type):
                failures.append(f"{doc_id}: 字段 {field} 类型应为 {expected_type}")
        if doc_id in seen:
            failures.append(f"{doc_id}: doc_id 重复")
        seen.add(doc_id)
        if doc_id.startswith("<no-id"):
            continue

        pdf_rel = f"eval/corpus/pdf/{row['filename']}"
        pdf_path = REPO / pdf_rel
        mirror_rel = f"eval/corpus/text/{doc_id}.pages.jsonl"
        mirror_path = REPO / mirror_rel

        # 2. sha256
        if pdf_path.exists():
            actual = sha256_of(pdf_path)
            if actual != row["sha256"]:
                failures.append(f"{doc_id}: sha256 不符（期望 {row['sha256'][:12]}… 实际 {actual[:12]}…）")
        elif row["in_repo"]:
            failures.append(f"{doc_id}: in_repo=true 但文件缺失 {pdf_rel}")

        # 3/4. 页数与文本层
        if mirror_path.exists():
            mirror_rows = [json.loads(l) for l in mirror_path.read_text(encoding="utf-8").splitlines() if l.strip()]
            if len(mirror_rows) != row["pages"]:
                failures.append(f"{doc_id}: 页数不符（manifest {row['pages']} / 镜像 {len(mirror_rows)}）")
            if mirror_rows:
                blanks = sum(1 for r in mirror_rows if len(str(r.get("text", "")).strip()) < 20)
                ratio = blanks / len(mirror_rows)
                if not row["text_layer_ok"] and ratio < SCAN_BLANK_THRESHOLD:
                    failures.append(
                        f"{doc_id}: 标记 text_layer_ok=false 但实测空页比例 {ratio:.2f}，疑似标记被误改"
                    )
                if row["text_layer_ok"] and ratio >= SCAN_BLANK_THRESHOLD:
                    failures.append(
                        f"{doc_id}: 标记 text_layer_ok=true 但实测空页比例 {ratio:.2f}，疑似扫描件被标为有文本层"
                    )
        elif row["in_repo"]:
            failures.append(f"{doc_id}: in_repo=true 但页级镜像缺失 {mirror_rel}")

        # 5. 合规防线：入库标志与 gitignore 必须一致
        if row["in_repo"]:
            in_repo_count += 1
        for rel, expect_ignored in ((pdf_rel, not row["in_repo"]), (mirror_rel, not row["in_repo"])):
            status = is_ignored(rel)
            if status is None:
                git_available = False
                continue
            if row["in_repo"] and status:
                failures.append(f"{doc_id}: in_repo=true 却被 gitignore 忽略，将不会随仓库发布 → {rel}")
            if not row["in_repo"] and not status:
                failures.append(f"{doc_id}: 不可再分发内容未被忽略，存在误发布风险 → {rel}")

    if not git_available:
        warnings.append("git 不可用，已跳过 gitignore 一致性检查（该项在 CI 中必须执行）")

    print(f"入库条目: {in_repo_count} / 仓库外条目: {len(rows) - in_repo_count}")
    print(f"页级镜像: {len(list(TEXT_DIR.glob('*.pages.jsonl')))} 个")

    for item in warnings:
        print(f"WARN {item}")
    if failures:
        print(f"\n失败 {len(failures)} 项：")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("\n语料完整性校验通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())