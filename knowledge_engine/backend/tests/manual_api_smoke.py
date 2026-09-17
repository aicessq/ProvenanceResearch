from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
WORK_DIR = Path(".manual-api-work")
WORK_DIR.mkdir(exist_ok=True)

sample1 = WORK_DIR / "cyber-law-v1.txt"
sample2 = WORK_DIR / "cyber-law-v2.txt"
sample1.write_text(
    "第一章 总则\n"
    "第二十一条 网络运营者应当按照网络安全等级保护制度的要求，履行安全保护义务。\n"
    "第二十二条 网络产品、服务应当符合相关国家标准的强制性要求。\n",
    encoding="utf-8",
)
sample2.write_text(
    "第一章 总则\n"
    "第二十一条 网络运营者应当按照网络安全等级保护制度的要求，履行安全保护义务。\n"
    "第二十二条 网络产品、服务应当符合相关国家标准的强制性要求。\n"
    "第二十三条 网络关键设备和网络安全专用产品应当按照相关国家标准进行安全认证或者安全检测。\n",
    encoding="utf-8",
)


def run(name: str, args: list[str]) -> str:
    print(f"\n===== {name} =====", flush=True)
    completed = subprocess.run(["curl.exe", *args], text=True, capture_output=True, encoding="utf-8", errors="replace")
    print(completed.stdout, flush=True)
    if completed.stderr:
        print(completed.stderr, file=sys.stderr, flush=True)
    if completed.returncode != 0:
        raise SystemExit(f"curl failed for {name}: {completed.returncode}")
    return completed.stdout


run("root health", ["-sS", f"{BASE_URL}/health"])
run("ready health", ["-sS", f"{BASE_URL}/api/v1/health/ready"])

upload_raw = run(
    "upload",
    [
        "-sS", "-X", "POST", f"{BASE_URL}/api/v1/documents/upload",
        "-F", f"file=@{sample1};type=text/plain",
        "-F", "title=手工测试网络安全法",
        "-F", "doc_type=law",
        "-F", "security_domain=network-security,compliance",
        "-F", "tags=manual,smoke",
    ],
)
upload = json.loads(upload_raw)
document_id = upload["document_id"]

print("\n等待 Celery ingest 处理 8 秒...", flush=True)
time.sleep(8)

run("query retrieve", ["-sS", "-X", "POST", f"{BASE_URL}/api/v1/query/retrieve", "-H", "Content-Type: application/json", "-d", json.dumps({"query": "网络运营者应当履行哪些安全保护义务？", "top_k": 5, "filters": {"doc_type": ["law"]}, "debug": True}, ensure_ascii=False)])
run("query rewrite", ["-sS", "-X", "POST", f"{BASE_URL}/api/v1/query/rewrite", "-H", "Content-Type: application/json", "-d", json.dumps({"query": "网络运营者安全义务", "filters": {"doc_type": ["law"]}}, ensure_ascii=False)])
run("query answer", ["-sS", "-X", "POST", f"{BASE_URL}/api/v1/query/answer", "-H", "Content-Type: application/json", "-d", json.dumps({"query": "网络运营者应当履行哪些安全保护义务？", "top_k": 5, "filters": {"doc_type": ["law"]}, "debug": True}, ensure_ascii=False)])

run("replace", ["-sS", "-X", "POST", f"{BASE_URL}/api/v1/documents/{document_id}/replace", "-F", f"file=@{sample2};type=text/plain", "-F", "change_summary=手工 smoke：新增第二十三条"])

print("\n等待 Celery replace 处理 8 秒...", flush=True)
time.sleep(8)

run("query answer after replace", ["-sS", "-X", "POST", f"{BASE_URL}/api/v1/query/answer", "-H", "Content-Type: application/json", "-d", json.dumps({"query": "第二十三条要求什么？", "top_k": 5, "filters": {"doc_type": ["law"]}, "debug": True}, ensure_ascii=False)])
run("eval run", ["-sS", "-X", "POST", f"{BASE_URL}/api/v1/eval/run", "-H", "Content-Type: application/json", "-d", "{}"])
run("soft delete", ["-sS", "-X", "DELETE", f"{BASE_URL}/api/v1/documents/{document_id}"])
