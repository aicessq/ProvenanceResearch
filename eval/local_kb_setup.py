"""Upload fixed original files into a separate real database and collection."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from uuid import uuid4
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "eval/benchmarks/local_kb_v1"
STATE = ROOT / ".env.run/local-eval"
BASE_URL = "http://127.0.0.1:8002"
DATABASE = "research_eval_local_v1"
COLLECTION = "eval_local_bge_768_v1"


def read_dataset():
    config = json.loads((DATA / "freeze.json").read_text(encoding="utf-8"))
    data = (DATA / "questions.jsonl").read_bytes()
    if hashlib.sha256(data).hexdigest() != config["questions_sha256"]:
        raise ValueError("Frozen questions changed")
    return config, [json.loads(line) for line in data.decode("utf-8").splitlines()]


def environment():
    load_dotenv(ROOT / ".env", override=False)
    env = dict(os.environ)
    env.update({"POSTGRES_DB": DATABASE, "REDIS_DB": "4", "QDRANT_COLLECTION": COLLECTION,
                "STORAGE_ROOT": str(STATE / "storage"), "HF_HUB_OFFLINE": "1",
                "TOKENIZERS_PARALLELISM": "false", "NO_PROXY": "localhost,127.0.0.1",
                "RERANKER_ENABLED": "false", "DEBUG": "false", "PYTHONPATH": str(ROOT)})
    if env.get("EMBEDDING_PROVIDER") != "local" or env.get("EMBEDDING_MODEL") != "BAAI/bge-base-en-v1.5" or env.get("EMBEDDING_VECTOR_SIZE") != "768":
        raise ValueError("This frozen benchmark requires the approved 768-dimensional local BGE configuration")
    return env


def save_json(path: Path, value):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def service_identity(env):
    paths = sorted((ROOT / "knowledge_engine/backend/app").rglob("*.py")) + [Path(__file__), ROOT / "eval/local_kb_service.py"]
    source_hash = hashlib.sha256()
    for path in paths:
        source_hash.update(str(path.relative_to(ROOT)).replace("\\", "/").encode())
        source_hash.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return {"nonce": env["LOCAL_KB_BENCHMARK_NONCE"], "database": env["POSTGRES_DB"],
            "collection": env["QDRANT_COLLECTION"], "redis_db": env["REDIS_DB"],
            "embedding_model_path": str(Path(env["EMBEDDING_MODEL_PATH"]).resolve()),
            "source_fingerprint": source_hash.hexdigest()}


def validate_server_identity(expected, actual):
    if actual != expected:
        raise RuntimeError("Benchmark server identity differs from recorded ownership/configuration")


def check_live_server(env):
    record = json.loads((STATE / "processes.json").read_text(encoding="utf-8"))
    expected_env = {**env, "LOCAL_KB_BENCHMARK_NONCE": record["identity"]["nonce"]}
    expected = service_identity(expected_env)
    validate_server_identity(expected, record["identity"])
    response = httpx.get(BASE_URL + "/__benchmark_identity", timeout=10)
    response.raise_for_status()
    validate_server_identity(expected, response.json())
    return expected


def start_services(env):
    import psycopg2
    from psycopg2 import sql
    # Only create the named evaluation database; never drop or truncate a user's database.
    connection = psycopg2.connect(host=env.get("POSTGRES_HOST", "127.0.0.1"), port=env.get("POSTGRES_PORT", "5432"),
                                 user=env["POSTGRES_USER"], password=env["POSTGRES_PASSWORD"], dbname="postgres")
    try:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_database WHERE datname=%s", (DATABASE,))
            if not cursor.fetchone():
                cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DATABASE)))
    finally:
        connection.close()
    STATE.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-X", "utf8", "-m", "eval.local_kb_service", "migrate"], cwd=ROOT, env=env, check=True)
    # Refuse to attach to a server we did not start and record for this benchmark.
    process_file = STATE / "processes.json"
    try:
        alive = httpx.get(BASE_URL + "/health", timeout=2).status_code == 200
    except httpx.HTTPError:
        alive = False
    if alive:
        if not process_file.exists():
            raise RuntimeError("Port 8002 already has an unowned server")
        check_live_server(env)
        return
    env = {**env, "LOCAL_KB_BENCHMARK_NONCE": uuid4().hex}
    processes = {}
    for mode in ("api", "worker"):
        with (STATE / (mode + ".log")).open("ab") as log:
            process = subprocess.Popen([sys.executable, "-X", "utf8", "-m", "eval.local_kb_service", mode],
                                       cwd=ROOT, env=env, stdout=log, stderr=log,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        processes[mode] = process.pid
    save_json(process_file, {"processes": processes, "identity": service_identity(env)})
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            ready = httpx.get(BASE_URL + "/api/v1/health/ready", timeout=15)
            if ready.status_code == 200 and ready.json().get("status") == "ok":
                check_live_server(env)
                return
        except httpx.HTTPError:
            pass
        time.sleep(2)
    raise RuntimeError("Isolated KB did not become ready; inspect local logs")


def prepare():
    config, _ = read_dataset()
    env = environment()
    start_services(env)
    binding_file = STATE / "bindings.json"
    bindings = json.loads(binding_file.read_text(encoding="utf-8")) if binding_file.exists() else {}
    with httpx.Client(base_url=BASE_URL, timeout=90) as client:
        for doc in config["documents"]:
            path = ROOT / "eval/corpus/pdf" / doc["filename"]
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != doc["sha256"]:
                raise ValueError("Original corpus hash mismatch: " + doc["doc_id"])
            if doc["doc_id"] not in bindings:
                with path.open("rb") as source:
                    response = client.post("/api/v1/documents/upload", files={"file": (path.name, source, "application/pdf" if path.suffix == ".pdf" else "text/plain")},
                                           data={"title": doc["doc_id"] + " | " + doc["title"], "doc_type": "law" if doc["lang"] == "zh" else "standard"})
                response.raise_for_status()
                bindings[doc["doc_id"]] = {**response.json(), "sha256": digest}
                save_json(binding_file, bindings)
            elif bindings[doc["doc_id"]]["sha256"] != digest:
                raise ValueError("Stored document binding differs from the frozen source")
        deadline = time.monotonic() + 900
        previous = None
        while True:
            statuses = {}
            for doc_id, binding in bindings.items():
                response = client.get("/api/v1/documents/tasks/" + binding["task_id"])
                response.raise_for_status()
                task = response.json()
                statuses[doc_id] = task["status"]
                if task["status"] == "failed":
                    raise RuntimeError("Ingest failed for " + doc_id + ": " + str(task.get("error_message")))
            completed = sum(s == "completed" for s in statuses.values())
            if completed != previous:
                print("Ingest completed:", completed, "/", len(bindings), flush=True)
                previous = completed
            if completed == len(config["documents"]):
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("Real corpus ingestion exceeded 900 seconds")
            time.sleep(3)
    return bindings


def audit():
    """Read-only provenance audit; no generation/retrieval performance queries."""
    import psycopg2
    config, questions = read_dataset()
    env = environment()
    identity = check_live_server(env)
    bindings = json.loads((STATE / "bindings.json").read_text(encoding="utf-8"))
    with psycopg2.connect(host=env["POSTGRES_HOST"], port=env["POSTGRES_PORT"], user=env["POSTGRES_USER"], password=env["POSTGRES_PASSWORD"], dbname=DATABASE) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT document_id::text,id::text,normalized_text FROM chunks WHERE chunk_type='child' AND is_active=true")
            chunks = [{"document_id": d, "chunk_id": c, "chunk_text": text} for d, c, text in cursor.fetchall()]
            cursor.execute("SELECT id::text FROM documents")
            ids = {row[0] for row in cursor.fetchall()}
    if ids != {value["document_id"] for value in bindings.values()} or len(ids) != len(config["documents"]):
        raise ValueError("Isolated database contains unexpected documents")
    from eval.local_kb_metrics import fact_hit
    missing = []
    for question in questions:
        for i, fact in enumerate(question["facts"]):
            if not any(fact_hit(fact, chunk, bindings) for chunk in chunks):
                missing.append({"question_id": question["id"], "fact": i, "doc_id": fact["doc_id"]})
    fingerprint = hashlib.sha256(json.dumps(sorted(chunks, key=lambda c: c["chunk_id"]), ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    points = []
    with httpx.Client(base_url=f"http://{env['QDRANT_HOST']}:{env.get('QDRANT_PORT', '6333')}", timeout=30) as client:
        info = client.get(f"/collections/{COLLECTION}")
        info.raise_for_status()
        vector_config = info.json()["result"]["config"]["params"]["vectors"]
        if vector_config["size"] != 768 or vector_config["distance"] != "Cosine":
            raise ValueError("Evaluation collection dimensions/distance changed")
        offset = None
        while True:
            body = {"limit": 256, "with_payload": True, "with_vector": False}
            if offset is not None:
                body["offset"] = offset
            response = client.post(f"/collections/{COLLECTION}/points/scroll", json=body)
            response.raise_for_status()
            page = response.json()["result"]
            points.extend(page["points"])
            offset = page["next_page_offset"]
            if offset is None:
                break
    if {str(p["id"]) for p in points} != {c["chunk_id"] for c in chunks}:
        raise ValueError("PostgreSQL and Qdrant membership differ")
    expected_identity = f"model={Path(env['EMBEDDING_MODEL_PATH']).name};dim=768;normalize=true;preprocess=v1"
    if {p["payload"].get("embedding_identity") for p in points} != {expected_identity}:
        raise ValueError("Unexpected Qdrant embedding identity")
    point_hash = hashlib.sha256(json.dumps(sorted(points, key=lambda p: str(p["id"])), ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    result = {"documents": len(ids), "child_chunks": len(chunks), "facts": sum(len(q["facts"]) for q in questions), "unmapped_facts": missing, "chunks_sha256": fingerprint,
              "qdrant_payload_sha256": point_hash, "index_identity": expected_identity, "server_identity": identity}
    save_json(STATE / "audit.json", result)
    print(json.dumps(result), flush=True)
    return result


if __name__ == "__main__":
    if sys.argv[1:] == ["audit"]:
        audit()
    else:
        prepare()
        audit()
