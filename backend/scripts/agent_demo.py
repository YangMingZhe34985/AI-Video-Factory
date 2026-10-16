"""Local, isolated mock demo: build frontend first, then run this script.

Creates demo data under backend/storage/agent-demo, never opens the normal DB.
Login: demo / agent-demo-only. No provider credentials or calls are used.
"""

import argparse
import os
import sys
import threading
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ["MODEL_ADAPTER_MODE"] = "mock"

from flask import send_from_directory  # noqa: E402
from app import create_app  # noqa: E402
from app.agent.worker import run_worker  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import User  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=5092)
    parser.add_argument("--storage", type=Path, default=BACKEND / "storage" / "agent-demo")
    args = parser.parse_args()
    storage = args.storage.resolve()
    frontend = BACKEND.parent / "frontend-vue" / "dist"
    if not (frontend / "index.html").is_file():
        raise SystemExit("Build frontend first: cd frontend-vue && npm run build")
    app = create_app(config_overrides={
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{(storage / 'demo.db').as_posix()}",
        "SQLALCHEMY_ENGINE_OPTIONS": {"connect_args": {"timeout": 30}},
        "STORAGE_ROOT": str(storage), "UPLOAD_FOLDER": str(storage / "uploads"),
        "AGENT_CHECKPOINT_PATH": str(storage / "checkpoints.sqlite"),
        "AGENT_MODE_ENABLED": True, "MODEL_ADAPTER_MODE": "mock", "API_AUTH_REQUIRED": True,
        "JWT_SECRET_KEY": "local-agent-demo-only-not-for-production", "AGENT_POLL_INTERVAL_SEC": 0.5,
        "JOB_QUEUE_ENABLED": True, "JOB_MAX_CONCURRENT_RUNS": 2,
        "POLL_INTERVAL_SEC": 0, "MAX_POLL_ROUNDS": 3, "VIDEO_COMPRESSION_ENABLED": False,
    })
    result = app.test_cli_runner().invoke(args=["init-db"])
    if result.exit_code:
        raise SystemExit(result.output)
    with app.app_context():
        if not User.query.filter_by(username="demo").first():
            user = User(username="demo")
            user.set_password("agent-demo-only")
            db.session.add(user)
            db.session.commit()

    @app.get("/")
    @app.get("/<path:path>")
    def frontend_route(path=""):
        if path.startswith("api/"):
            from flask import abort
            abort(404)
        if path.startswith("assets/"):
            return send_from_directory(frontend, path)
        return send_from_directory(frontend, "index.html")

    def work():
        with app.app_context():
            run_worker()
    threading.Thread(target=work, daemon=True).start()
    print(f"Agent Studio mock demo: http://127.0.0.1:{args.port}/agent-studio (demo / agent-demo-only)")
    app.run(host="127.0.0.1", port=args.port, use_reloader=False, debug=False)


if __name__ == "__main__":
    main()
