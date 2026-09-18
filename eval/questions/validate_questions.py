#!/usr/bin/env python3
"""校验 eval/questions/questions.v1.jsonl。

检查项（对应任务要求）：
1. schema 完整性与字段类型（id/question/type/expected_behavior/expected_locator/
   required_points/forbidden_points/refuse_reason/difficulty/verified/notes）；
2. 题型配额（single_source 15 / multi_hop 10 / external_only 8 / version_contrast 5 /
   insufficient 10–15 / near_miss 5–8，总数 40–60）；
3. expected_locator 指向的文档与页在语料中真实存在（对照 manifest 与页级镜像）；
4. required_points 每条能在其 expected_locator 指向的页文本中逐字匹配
   （仅忽略空白差异，不做任何同义改写；换行断词的连字符/连字按原字符保留）；
5. forbidden_points 不与 required_points 冲突（空白归一后无子串包含）；
6. 结构语义：refuse_reason 与 expected_behavior 的一致性、各题型 locator 形态、
   external_only 的目标确属语料之外。

退出码：0 全部通过；1 存在失败条目。失败原因定位到字段。
纯离线脚本：不联网、不依赖第三方库（除标准库）。
"""

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
QUESTIONS = HERE / "questions.v1.jsonl"
CORPUS = HERE.parent / "corpus"
MANIFEST = CORPUS / "manifest.jsonl"

TYPES = ("single_source", "multi_hop", "external_only", "version_contrast", "insufficient", "near_miss")
BEHAVIORS = ("answered", "partial", "refused")
REFUSE_REASONS = ("topic_absent", "missing_key_fact", "requires_prediction")
QUOTA = {  # 任务定稿配额；如用户日后调整题目集，请同步修改这里
    "single_source": (15, 15), "multi_hop": (10, 10), "external_only": (8, 8),
    "version_contrast": (5, 5), "insufficient": (10, 15), "near_miss": (5, 8),
}
TOTAL_RANGE = (40, 60)


def strip_ws(s: str) -> str:
    return re.sub(r"\s+", "", s)


def load_manifest():
    if not MANIFEST.exists():
        sys.exit(f"找不到 {MANIFEST}")
    entries = [json.loads(l) for l in MANIFEST.read_text(encoding="utf-8").splitlines() if l.strip()]
    return {e["doc_id"]: e for e in entries}


def load_page_texts():
    texts = {}
    for f in sorted((CORPUS / "text").glob("*.pages.jsonl")):
        doc_id = f.name[:- len(".pages.jsonl")]
        pages = {}
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                pages[r["page"]] = r["text"]
        texts[doc_id] = pages
    return texts


def validate(question, manifest, page_texts):
    """返回该题的错误列表（空 = 通过）。"""
    errs = []

    def field(name, expect, label):
        if name not in question:
            errs.append(f"缺字段 {name}")
            return None
        v = question[name]
        if isinstance(expect, type):  # list/str/bool 等类型：isinstance 检查
            ok = isinstance(v, expect)
        else:  # lambda 谓词
            ok = bool(expect(v))
        if not ok:
            errs.append(f"字段 {name} 类型错误: {v!r}")
            return None
        return v

    qid = field("id", lambda v: isinstance(v, str) and re.fullmatch(r"q\d{3,}", v) and True or bool(v), "id")
    field("question", lambda v: isinstance(v, str) and len(v.strip()) > 0, "question")
    qtype = field("type", lambda v: v in TYPES, "type")
    behavior = field("expected_behavior", lambda v: v in BEHAVIORS, "expected_behavior")
    locators = field("expected_locator", list, "expected_locator")
    required = field("required_points", list, "required_points")
    forbidden = field("forbidden_points", list, "forbidden_points")
    refuse_reason = field("refuse_reason", lambda v: v is None or v in REFUSE_REASONS, "refuse_reason")
    field("difficulty", lambda v: isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 5, "difficulty")
    field("verified", bool, "verified")
    field("notes", str, "notes")
    if errs:
        return errs
    for name, arr in (("required_points", required), ("forbidden_points", forbidden)):
        for i, p in enumerate(arr):
            if not isinstance(p, str) or not p.strip():
                errs.append(f"{name}[{i}] 非非空字符串")
    if errs:
        return errs

    # ---- 语义规则 ----
    if qtype == "insufficient":
        if behavior != "refused":
            errs.append(f"expected_behavior 应为 refused，实际 {behavior}")
        if refuse_reason not in REFUSE_REASONS:
            errs.append(f"refuse_reason 必填且取值受限，实际 {refuse_reason!r}")
    else:
        if behavior == "refused":
            errs.append(f"非 insufficient 题不允许 refused")
        if refuse_reason is not None:
            errs.append(f"非 insufficient 题 refuse_reason 应为 null，实际 {refuse_reason!r}")

    # ---- locator 形态 ----
    in_corpus_locs, external_locs = [], []
    for i, loc_ in enumerate(locators):
        if not isinstance(loc_, dict):
            errs.append(f"expected_locator[{i}] 非对象")
            continue
        if loc_.get("external"):
            url = loc_.get("url")
            if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                errs.append(f"expected_locator[{i}].url 非合法 http(s) 地址: {url!r}")
            external_locs.append(loc_)
            continue
        doc_id, page = loc_.get("doc_id"), loc_.get("page")
        if doc_id not in manifest:
            errs.append(f"expected_locator[{i}].doc_id 不在 manifest: {doc_id!r}")
            continue
        if not isinstance(page, int) or page < 1:
            errs.append(f"expected_locator[{i}].page 非法: {page!r}")
            continue
        declared = manifest[doc_id]["pages"]
        if declared is not None and page > declared:
            errs.append(f"expected_locator[{i}].page {page} 超出 {doc_id} 总页数 {declared}")
        pages = page_texts.get(doc_id)
        if pages is None:
            hint = "（arXiv 镜像被 gitignore：先跑 download_corpus.py 与 extract_text.py）" \
                if not manifest[doc_id]["in_repo"] else ""
            errs.append(f"{doc_id} 缺页级文本镜像{hint}")
        elif page not in pages:
            errs.append(f"{doc_id} 镜像中无第 {page} 页")
        in_corpus_locs.append((loc_, doc_id, page))

    if qtype == "external_only":
        if in_corpus_locs:
            errs.append("external_only 题的 locator 不得指向语料内文档")
        if not external_locs:
            errs.append("external_only 题至少需要一个 external locator")
        for loc_ in external_locs:
            ax = loc_.get("arxiv_id")
            if ax:
                for doc_id, e in manifest.items():
                    src = e.get("source_url", "")
                    if ax in src and e["category"] == "arxiv":
                        errs.append(f"external locator 的 arxiv_id {ax} 已在语料中（{doc_id}），不是外部题")
    else:
        if external_locs:
            errs.append(f"{qtype} 题不应使用 external locator")
        if qtype == "single_source" and len(in_corpus_locs) != 1:
            errs.append(f"single_source 题应恰有 1 个语料内 locator，实际 {len(in_corpus_locs)}")
        if qtype in ("multi_hop", "version_contrast"):
            if len(in_corpus_locs) < 2:
                errs.append(f"{qtype} 题应至少有 2 个语料内 locator")
            elif len({d for _, d, _ in in_corpus_locs}) < 2:
                errs.append(f"{qtype} 题的多个 locator 应指向不同文档")
        if qtype == "near_miss" and not in_corpus_locs:
            errs.append("near_miss 题至少需要 1 个语料内 locator")
        if qtype == "insufficient" and len(in_corpus_locs) > 1:
            errs.append("insufficient 题至多 1 个语料内 locator")
        if qtype == "insufficient" and not locators and refuse_reason != "topic_absent":
            errs.append("insufficient 题无 locator 时 refuse_reason 必须是 topic_absent")
        if qtype != "insufficient" and not in_corpus_locs:
            errs.append(f"{qtype} 题缺少语料内 locator")

    # ---- required_points 逐字匹配（忽略空白差异） ----
    if qtype != "external_only" and in_corpus_locs:
        if qtype != "insufficient" and not required:
            errs.append(f"{qtype} 题的 required_points 不得为空")
        corpus_pages = [page_texts[d][p] for _, d, p in in_corpus_locs if d in page_texts and p in page_texts[d]]
        joined = strip_ws("".join(corpus_pages)) if corpus_pages else ""
        for i, point in enumerate(required):
            if strip_ws(point) not in joined:
                errs.append(f"required_points[{i}] 未能逐字命中定位页文本（忽略空白后仍不匹配）")
    if qtype == "external_only":
        for i, point in enumerate(required):
            if len(point) > 300:
                errs.append(f"required_points[{i}] 过长（>300 字符，外部题应给关键要点）")

    # ---- forbidden 与 required 冲突 ----
    # 冲突定义：某 forbidden（忽略空白）是某 required 的子串——此时任何含 required
    # 的正确回答都会同时命中 forbidden，题目不可判。反向包含（forbidden 是包含
    # required 的更长“错误整句”，用于拦截主体/情节对调）不算冲突。
    for i, f_ in enumerate(forbidden):
        for j, r_ in enumerate(required):
            if strip_ws(f_) and strip_ws(f_) in strip_ws(r_):
                errs.append(f"forbidden_points[{i}] 是 required_points[{j}] 的子串，评分必然误伤，构成冲突")
    return errs


def main():
    if not QUESTIONS.exists():
        sys.exit(f"找不到 {QUESTIONS}")
    questions = []
    for n, line in enumerate(QUESTIONS.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            questions.append(json.loads(line))
        except json.JSONDecodeError as e:
            print(f"[FAIL] 第 {n} 行 JSON 解析失败: {e}")
            return 1

    ids = [q.get("id") for q in questions]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        print(f"[FAIL] id 重复: {sorted(dup)}")
        return 1

    manifest = load_manifest()
    page_texts = load_page_texts()

    failures = []
    for q in questions:
        errs = validate(q, manifest, page_texts)
        status = "PASS" if not errs else "FAIL"
        print(f"[{status}] {q.get('id', '???')} {q.get('type', '?')}: {q.get('question', '')[:40]}")
        for e in errs:
            print(f"       - {e}")
        if errs:
            failures.append(q.get("id"))

    # ---- 配额 ----
    from collections import Counter
    counts = Counter(q.get("type") for q in questions)
    print("\n===== 题型配额 =====")
    quota_ok = True
    for t in TYPES:
        lo, hi = QUOTA[t]
        n = counts.get(t, 0)
        mark = "OK" if lo <= n <= hi else "FAIL"
        if mark == "FAIL":
            quota_ok = False
        print(f"  {t:16s} {n:3d} (要求 {lo}–{hi}) {mark}")
    total = len(questions)
    lo, hi = TOTAL_RANGE
    if not (lo <= total <= hi):
        quota_ok = False
    print(f"  总数             {total:3d} (要求 {lo}–{hi}) {'OK' if lo <= total <= hi else 'FAIL'}")
    print(f"  verified=true 数量: {sum(1 for q in questions if q.get('verified'))}（应为 0，仅用户人工核对后可置 true）")

    if failures:
        print(f"\n失败条目 {len(failures)} 个: {failures}")
        return 1
    if not quota_ok:
        print("\n配额不满足。")
        return 1
    print("\n全部条目通过校验。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
