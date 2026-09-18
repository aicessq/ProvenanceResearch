#!/usr/bin/env python3
"""按 manifest.jsonl 下载评测语料（幂等、可重跑）。

用法：
  python3 download_corpus.py              # 校验模式：缺文件则下载，已有则核对 sha256
  python3 download_corpus.py --record     # 引导模式：sha256 为 null 的条目下载后回写哈希（构建期用一次）

约定：
- 每行 manifest 一个文档；目标文件为 pdf/<filename>。
- 已存在且 sha256 匹配 → 跳过；不匹配 → 重新下载并复核，仍不符则记为失败。
- 只允许 http(s)；重定向 ≤5 跳；单文件 ≤50MB；每次请求带 User-Agent 与超时。
- 失败重试 ≤3 次（指数退避 1s/2s/4s + 抖动）；arXiv 请求间隔 ≥3 秒。
- 下载失败在报告中逐条列出，绝不以其他文档或生成内容顶替。

flk.npc.gov.cn 来源（source_url 形如 https://flk.npc.gov.cn/detail?id=<bbbs>...）走三步链路：
  1) GET /law-search/download/pc?format=pdf&bbbs=<id>&fileId=  → JSON data.url（1 小时有效的预签名地址）
  2) GET 预签名地址下载 PDF
  其余来源直接 GET source_url。

注意：flk 的 download/pc 接口不接受 orderByParam 一类多余字段；搜索接口（search/list）
若在请求体里带 orderByParam 会触发服务端 500，本脚本不调用搜索接口（bbbs 已固化在 manifest）。
"""

import argparse
import hashlib
import json
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CORPUS_DIR = Path(__file__).resolve().parent
MANIFEST = CORPUS_DIR / "manifest.jsonl"
PDF_DIR = CORPUS_DIR / "pdf"

USER_AGENT = "ProvenanceResearch-eval/0.1 (corpus fetcher; academic eval corpus)"
MAX_REDIRECTS = 5
MAX_BYTES = 50 * 1024 * 1024  # 50MB
RETRIES = 3
ARXIV_MIN_INTERVAL = 3.0  # 秒，arxiv.org 礼貌间隔
FLK_MIN_INTERVAL = 0.5     # 秒，flk API 间隔

_last_request = {"arxiv.org": 0.0, "flk.npc.gov.cn": 0.0}


class TooManyRedirects(Exception):
    pass


class _CappedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """限制重定向跳数（urllib 默认最多 10，这里收紧到 MAX_REDIRECTS）。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if req.redirect_count >= MAX_REDIRECTS:  # type: ignore[attr-defined]
            raise TooManyRedirects(f"> {MAX_REDIRECTS} redirects: {newurl}")
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            new.redirect_count = getattr(req, "redirect_count", 0) + 1  # type: ignore[attr-defined]
        return new


_opener = urllib.request.build_opener(_CappedRedirectHandler)


def _throttle(url: str) -> None:
    host = urllib.parse.urlsplit(url).hostname or ""
    for key, min_gap in (("arxiv.org", ARXIV_MIN_INTERVAL), ("flk.npc.gov.cn", FLK_MIN_INTERVAL)):
        if host.endswith(key):
            gap = time.monotonic() - _last_request[key]
            if gap < min_gap:
                time.sleep(min_gap - gap)
            _last_request[key] = time.monotonic()
            return


def http_get(url: str, timeout: float = 60.0, max_bytes: int = MAX_BYTES, accept: str = "*/*"):
    """GET 返回 bytes；强制 http(s)、节流、超时与大小上限。"""
    scheme = urllib.parse.urlsplit(url).scheme
    if scheme not in ("http", "https"):
        raise ValueError(f"非 http(s) 地址: {url}")
    _throttle(url)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    with _opener.open(req, timeout=timeout) as resp:
        data = b""
        while True:
            chunk = resp.read(64 * 1024)
            if not chunk:
                break
            data += chunk
            if len(data) > max_bytes:
                raise ValueError(f"超过单文件大小上限 {max_bytes} 字节: {url}")
        return data


def http_get_json(url: str, timeout: float = 30.0):
    return json.loads(http_get(url, timeout=timeout, max_bytes=2 * 1024 * 1024, accept="application/json").decode("utf-8"))


def flk_pdf_url(source_url: str) -> str:
    """flk detail 页 URL → 预签名 PDF 下载地址。"""
    qs = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(source_url).query))
    bbbs = qs.get("id")
    if not bbbs:
        raise ValueError(f"flk source_url 缺少 id 参数: {source_url}")
    api = f"https://flk.npc.gov.cn/law-search/download/pc?format=pdf&bbbs={urllib.parse.quote(bbbs)}&fileId="
    d = http_get_json(api)
    url = (d.get("data") or {}).get("url")
    if d.get("code") != 200 or not url:
        raise RuntimeError(f"flk download/pc 失败: {d.get('msg')} (bbbs={bbbs})")
    return url


def fetch_bytes(entry: dict) -> bytes:
    """按来源类型取回原始字节。失败由调用方重试。"""
    url = entry["source_url"]
    if urllib.parse.urlsplit(url).hostname and urllib.parse.urlsplit(url).hostname.endswith("flk.npc.gov.cn"):
        return http_get(flk_pdf_url(url), timeout=120.0)
    return http_get(url, timeout=120.0)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download_entry(entry: dict, record: bool) -> tuple[str, str]:
    """返回 (status, message)。status ∈ ok / skip / mismatch / fail。"""
    doc_id = entry["doc_id"]
    target = PDF_DIR / entry["filename"]
    target.parent.mkdir(parents=True, exist_ok=True)
    expected = entry.get("sha256")

    if target.exists() and expected:
        actual = sha256_hex(target.read_bytes())
        if actual == expected:
            return "skip", f"sha256 匹配，跳过 ({target.name})"
        print(f"  [mismatch] {doc_id}: 本地 {actual[:8]} != manifest {expected[:8]}，重新下载", flush=True)

    last_err = None
    for attempt in range(1, RETRIES + 1):
        try:
            data = fetch_bytes(entry)
            actual = sha256_hex(data)
            if expected and actual != expected:
                # 重新下载仍不一致：如实报告，不覆盖既有文件
                if target.exists():
                    target.rename(target.with_suffix(target.suffix + ".mismatched"))
                target.write_bytes(data)
                return "mismatch", f"下载后 sha256 {actual[:8]} 与 manifest {expected[:8]} 不符"
            target.write_bytes(data)
            if record and not expected:
                entry["sha256"] = actual
                return "ok-recorded", f"{len(data)} bytes, sha256={actual[:8]}（已回写 manifest）"
            return "ok", f"{len(data)} bytes, sha256={actual[:8]}"
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError, RuntimeError,
                json.JSONDecodeError, TooManyRedirects, TimeoutError, OSError) as e:
            last_err = e
            if attempt < RETRIES:
                backoff = (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                print(f"  [retry {attempt}/{RETRIES}] {doc_id}: {e}，{backoff:.1f}s 后重试", flush=True)
                time.sleep(backoff)
    return "fail", f"重试 {RETRIES} 次仍失败: {last_err}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--record", action="store_true",
                    help="引导模式：sha256 为 null 的条目下载后把哈希回写 manifest.jsonl")
    ap.add_argument("--only", help="只处理指定 doc_id（调试用）")
    args = ap.parse_args()

    if not MANIFEST.exists():
        print(f"找不到 {MANIFEST}", file=sys.stderr)
        return 2

    entries = [json.loads(line) for line in MANIFEST.read_text(encoding="utf-8").splitlines() if line.strip()]
    results = {"skip": [], "ok": [], "ok-recorded": [], "mismatch": [], "fail": []}

    for entry in entries:
        if args.only and entry["doc_id"] != args.only:
            continue
        print(f"[{entry['doc_id']}] {entry['title']}", flush=True)
        status, msg = download_entry(entry, record=args.record)
        results.setdefault(status, []).append((entry["doc_id"], msg))
        print(f"  -> {status}: {msg}", flush=True)

    if args.record and results["ok-recorded"]:
        with MANIFEST.open("w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print(f"\n已回写 {len(results['ok-recorded'])} 条 sha256 到 {MANIFEST.name}")

    print("\n===== 下载报告 =====")
    print(f"跳过(已匹配): {len(results['skip'])} | 成功: {len(results['ok'])} | "
          f"新记录: {len(results['ok-recorded'])} | 哈希不符: {len(results['mismatch'])} | 失败: {len(results['fail'])}")
    for status in ("mismatch", "fail"):
        for doc_id, msg in results[status]:
            print(f"  [{status}] {doc_id}: {msg}")
    if not results["mismatch"] and not results["fail"]:
        print("全部条目获取成功且校验通过。")
        return 0
    print("\n存在失败或不符条目——按纪律不做任何顶替，请人工处理后再重跑。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
