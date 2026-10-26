"""Isolated real KE processes. Environment is supplied by local_kb_setup."""
import os
import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    backend = root / "knowledge_engine/backend"
    sys.path.insert(0, str(backend))
    os.chdir(backend)
    mode = sys.argv[1]
    if mode == "migrate":
        from alembic import command
        from alembic.config import Config
        command.upgrade(Config("alembic.ini"), "head")
    elif mode == "api":
        import uvicorn
        from app.main import app
        from eval.local_kb_setup import service_identity
        identity = service_identity(os.environ)

        @app.get("/__benchmark_identity", include_in_schema=False)
        def benchmark_identity():
            return identity

        uvicorn.run(app, host="127.0.0.1", port=8002, log_level="warning")
    elif mode == "worker":
        from app.workers.celery_app import celery_app
        celery_app.worker_main(["worker", "--pool=solo", "--concurrency=1", "--loglevel=warning", "--hostname=eval-local-kb@%h"])
    else:
        raise ValueError("Unknown isolated service mode")


if __name__ == "__main__":
    main()
