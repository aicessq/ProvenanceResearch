#!/usr/bin/env python3
"""校验仓库级契约：配置模板、路线图阶段、文档链接、决策日志只追加、敏感路径忽略状态。

为什么需要它：这个仓库已经出现过两次"文档互相矛盾"——design 与 roadmap 对 UI 的定位冲突、
README 要求 `cp .env.example .env` 而文件不存在。这类问题无法靠单元测试发现，
但会直接误导后续实现与面试阅读者，因此固化成可执行检查。

检查项：
1. `.env.example`：本地模型路径必须不存在；键名唯一；所有密钥类变量为空；
   LLM/EMBEDDING/RERANKER/OCR/VISION 各自的 provider/model/version/base_url/key/timeout/retry 字段齐全；
   出站授权默认关闭且授权映射为空；Agent 预算与入库限制为合法正整数。
2. `docs/roadmap.md`：每个阶段都必须有"目标/前置/验收"三段，防止未定义验收就进入实现。
3. Markdown 相对链接与锚点可达。**仅检查本仓库自撰文件**（顶层文档、docs/、三个占位目录、
   eval/ 下的自撰文档）；不扫描两个子项目的历史文档，避免对旧内容施加新的门禁。
4. `docs/decisions.md` 只追加：当前内容必须以 HEAD 版本为前缀，防止历史决策被改写。
5. 敏感路径必须被忽略：凭证、运行时配置库、本地工具状态、个人学习材料。

退出码：0 通过；1 存在失败项。纯离线、只用标准库。
"""

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENV_EXAMPLE = REPO / ".env.example"
ROADMAP = REPO / "docs" / "roadmap.md"
DECISIONS = REPO / "docs" / "decisions.md"

CLOUD_CAPABILITIES = ("LLM", "EMBEDDING", "RERANKER", "OCR", "VISION")
CAPABILITY_FIELDS = (
    "PROVIDER",
    "MODEL",
    "MODEL_VERSION",
    "BASE_URL",
    "API_KEY",
    "TIMEOUT_SECONDS",
    "MAX_RETRIES",
)
FORBIDDEN_ENV_KEYS = ("EMBEDDING_MODEL_PATH", "RERANKER_MODEL_PATH", "EMBEDDING_VECTOR_SIZE")

ROADMAP_PHASES = (
    "P0（历史）",
    "基线轮",
    "P1（历史）",
    "P2（历史）",
    "P0R",
    "P3a",
    "P3b",
    "P3c",
    "P3d",
    "P4",
    "P5",
)

# 自撰文档：这些文件由本仓库维护，链接必须可达。
SELF_AUTHORED_DOCS = (
    "README.md",
    "AGENTS.md",
    "docs/design.md",
    "docs/roadmap.md",
    "docs/decisions.md",
    "docs/testing.md",
    "frontend/README.md",
    "eval/README.md",
    "eval/corpus/README.md",
    "eval/questions/README.md",
    "eval/questions/REVIEW_CHECKLIST.md",
    "tests_bridge/README.md",
)

# 这些路径无论何时都必须处于忽略状态（凭证 / 运行时状态 / 个人材料）。
MUST_BE_IGNORED = (
    ".env",
    "researcher/deep_research_system/.env",
    "researcher/deep_research_system/data/config.db",
    ".zcode/plans/plan.md",
    "knowledge_engine/Teach_Learn/lessons/0001-read-the-project-map.html",
    "researcher/project_course/index.html",
    "researcher/project_interview_guide.html",
    "knowledge_engine/Doc/Phase10面试学习版.html",
    "eval/corpus/pdf/arxiv/2304.09848v1.pdf",
)


def git(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)


def slugify(heading: str) -> str:
    text = heading.strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def check_env_example(failures: list[str]) -> None:
    if not ENV_EXAMPLE.exists():
        failures.append(".env.example 不存在（README 的快速开始依赖它）")
        return
    values: dict[str, str] = {}
    for lineno, line in enumerate(ENV_EXAMPLE.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Z][A-Z0-9_]*)=(.*)", stripped)
        if not match:
            failures.append(f".env.example 第 {lineno} 行不是 KEY=VALUE 形式: {stripped[:40]}")
            continue
        key, value = match.groups()
        if key in values:
            failures.append(f".env.example 键名重复: {key}")
        values[key] = value

    for key in FORBIDDEN_ENV_KEYS:
        if key in values:
            failures.append(f".env.example 重新引入了本地模型路径变量: {key}")
    for key, value in values.items():
        if key.endswith("_API_KEY") or key.endswith("_ENCRYPTION_KEY"):
            if value != "":
                failures.append(f".env.example 密钥类变量必须留空（模板不得含真实值）: {key}")
    for capability in CLOUD_CAPABILITIES:
        for field in CAPABILITY_FIELDS:
            key = f"{capability}_{field}"
            if key not in values:
                failures.append(f".env.example 缺少云能力字段: {key}")
            elif field in ("PROVIDER", "MODEL", "MODEL_VERSION", "BASE_URL", "API_KEY") and values[key] != "":
                failures.append(f".env.example {key} 应为空占位（供应商由用户后续选择）")
    if values.get("CLOUD_DATA_UPLOAD_ALLOWED") != "false":
        failures.append(".env.example 出站授权默认必须为 false")
    if values.get("CLOUD_DATA_APPROVALS_JSON") != "{}":
        failures.append(".env.example 出站授权映射默认必须为空对象")
    if values.get("RERANKER_ENABLED") != "false":
        failures.append(".env.example reranker 默认应关闭（仅保留 RRF）")
    for key in (
        "AGENT_MAX_ROUNDS",
        "AGENT_MAX_TOOL_CALLS",
        "AGENT_MAX_MODEL_TOKENS",
        "AGENT_DEADLINE_SECONDS",
        "AGENT_MAX_CONCURRENCY",
        "DOCUMENT_MAX_PAGES",
        "DOCUMENT_MAX_UPLOAD_MB",
        "IMAGE_MAX_PIXELS",
        "INGEST_MAX_CONCURRENCY",
    ):
        if key not in values:
            failures.append(f".env.example 缺少受限执行参数: {key}")
        elif not values[key].isdigit() or int(values[key]) <= 0:
            failures.append(f".env.example {key} 必须为正整数，实际为 {values[key]!r}")


def check_roadmap(failures: list[str]) -> None:
    if not ROADMAP.exists():
        failures.append("docs/roadmap.md 不存在（AGENTS.md 的阶段验收引用它）")
        return
    text = ROADMAP.read_text(encoding="utf-8")
    sections = re.split(r"(?m)^## ", text)[1:]
    for phase in ROADMAP_PHASES:
        section = next((s for s in sections if s.startswith(phase + " ") or s.startswith(phase)), None)
        if section is None:
            failures.append(f"roadmap 缺少阶段: {phase}")
            continue
        for label in ("**目标**", "**前置**", "**验收**"):
            if label not in section:
                failures.append(f"roadmap 阶段 {phase} 缺少 {label} 段")


def check_links(failures: list[str]) -> None:
    heads_cache: dict[Path, set[str]] = {}
    for rel in SELF_AUTHORED_DOCS:
        path = REPO / rel
        if not path.exists():
            failures.append(f"自撰文档缺失: {rel}")
            continue
        text = path.read_text(encoding="utf-8")
        if text.count("```") % 2 != 0:
            failures.append(f"{rel}: 代码围栏数量为奇数（``` 未闭合）")
        if not text.endswith("\n"):
            failures.append(f"{rel}: 文件应以换行结尾")
        for target in re.findall(r"\]\(([^)]+)\)", text):
            if "://" in target or target.startswith("#"):
                continue
            dest, _, anchor = target.partition("#")
            resolved = (path.parent / dest).resolve() if dest else path
            if not resolved.exists():
                failures.append(f"{rel}: 链接指向不存在的路径 {target}")
                continue
            if anchor and resolved.suffix == ".md":
                if resolved not in heads_cache:
                    heads_cache[resolved] = {
                        slugify(h)
                        for h in re.findall(r"(?m)^#{1,6} (.+)$", resolved.read_text(encoding="utf-8"))
                    }
                if anchor not in heads_cache[resolved]:
                    failures.append(f"{rel}: 锚点不存在 {target}")


def check_decisions_append_only(failures: list[str]) -> None:
    if not DECISIONS.exists():
        failures.append("docs/decisions.md 不存在")
        return
    current = DECISIONS.read_text(encoding="utf-8")
    head = git(["show", "HEAD:docs/decisions.md"])
    if head.returncode != 0:
        return  # 首次提交前没有可比基线
    if not current.startswith(head.stdout):
        failures.append("docs/decisions.md 不是只追加：当前内容不再以 HEAD 版本为前缀（历史可能被改写）")


def check_sensitive_paths(failures: list[str]) -> None:
    for rel in MUST_BE_IGNORED:
        result = git(["check-ignore", "-q", rel])
        if result.returncode != 0:
            failures.append(f"敏感路径未被忽略: {rel}（公开仓库前必须保持忽略状态）")


def main() -> int:
    failures: list[str] = []
    check_env_example(failures)
    check_roadmap(failures)
    check_links(failures)
    check_decisions_append_only(failures)
    check_sensitive_paths(failures)

    print(f"自撰文档链接检查: {len(SELF_AUTHORED_DOCS)} 个文件")
    print(f"敏感路径忽略检查: {len(MUST_BE_IGNORED)} 条")
    print(f"云能力字段检查: {' / '.join(CLOUD_CAPABILITIES)}")
    if failures:
        print(f"\n失败 {len(failures)} 项：")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("\n仓库契约校验通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())