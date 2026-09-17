from __future__ import annotations

import json
import mimetypes
import time
import uuid
from pathlib import Path
from urllib import request as urlrequest
from urllib.error import HTTPError

BASE_URL = "http://127.0.0.1:8000"
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


def http_json(name: str, method: str, path: str, payload: dict | None = None) -> tuple[int, str]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urlrequest.Request(f"{BASE_URL}{path}", data=data, headers=headers, method=method)
    return send(name, req)


def http_multipart(name: str, path: str, fields: dict[str, str], files: dict[str, Path]) -> tuple[int, str]:
    boundary = f"----manual-{uuid.uuid4().hex}"
    body = bytearray()
    for key, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
        body.extend(str(value).encode("utf-8"))
        body.extend(b"\r\n")
    for key, file_path in files.items():
        body.extend(f"--{boundary}\r\n".encode())
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        body.extend(
            f'Content-Disposition: form-data; name="{key}"; filename="{file_path.name}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n".encode()
        )
        body.extend(file_path.read_bytes())
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    req = urlrequest.Request(
        f"{BASE_URL}{path}",
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    return send(name, req)


def send(name: str, req: urlrequest.Request) -> tuple[int, str]:
    print(f"\n===== {name} =====", flush=True)
    try:
        with urlrequest.urlopen(req, timeout=30) as response:
            text = response.read().decode("utf-8", errors="replace")
            print(text, flush=True)
            return response.status, text
    except HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        print(text, flush=True)
        return exc.code, text


results: list[tuple[str, int, str]] = []

for name, method, path, payload in [
    ("root health", "GET", "/health", None),
    ("ready health", "GET", "/api/v1/health/ready", None),
]:
    status, text = http_json(name, method, path, payload)
    results.append((name, status, text))

status, upload_raw = http_multipart(
    "upload",
    "/api/v1/documents/upload",
    {
        "title": "手工测试网络安全法",
        "doc_type": "law",
        "security_domain": "network-security,compliance",
        "tags": "manual,smoke",
    },
    {"file": sample1},
)
results.append(("upload", status, upload_raw))
upload = json.loads(upload_raw)
document_id = upload["document_id"]

print("\n等待 Celery ingest 处理 8 秒...", flush=True)
time.sleep(8)

for name, payload in [
    ("query retrieve", {"query": "网络运营者应当履行哪些安全保护义务？", "top_k": 5, "filters": {"doc_type": ["law"]}, "debug": True}),
    ("query rewrite", {"query": "网络运营者安全义务", "filters": {"doc_type": ["law"]}}),
    ("query answer", {"query": "网络运营者应当履行哪些安全保护义务？", "top_k": 5, "filters": {"doc_type": ["law"]}, "debug": True}),
]:
    endpoint = "/api/v1/query/rewrite" if name == "query rewrite" else ("/api/v1/query/retrieve" if name == "query retrieve" else "/api/v1/query/answer")
    status, text = http_json(name, "POST", endpoint, payload)
    results.append((name, status, text))

status, replace_raw = http_multipart(
    "replace",
    f"/api/v1/documents/{document_id}/replace",
    {"change_summary": "手工 smoke：新增第二十三条"},
    {"file": sample2},
)
results.append(("replace", status, replace_raw))

print("\n等待 Celery replace 处理 8 秒...", flush=True)
time.sleep(8)

for name, method, path, payload in [
    ("query answer after replace", "POST", "/api/v1/query/answer", {"query": "第二十三条要求什么？", "top_k": 5, "filters": {"doc_type": ["law"]}, "debug": True}),
    ("eval run", "POST", "/api/v1/eval/run", {}),
    ("soft delete", "DELETE", f"/api/v1/documents/{document_id}", None),
]:
    status, text = http_json(name, method, path, payload)
    results.append((name, status, text))

print("\n===== summary =====")
for name, status, _text in results:
    print(f"{name}: HTTP {status}")

if any(status >= 500 for _name, status, _text in results):
    raise SystemExit(1)
