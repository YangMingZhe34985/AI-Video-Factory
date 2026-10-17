"""The shared local configuration must not depend on a worker's launch directory."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.mark.parametrize("cwd_name", [".", "backend", "elsewhere"])
@pytest.mark.parametrize("process_override", [False, True])
def test_root_env_is_shared_across_launch_directories(tmp_path, cwd_name, process_override):
    project = tmp_path / "project"
    app_dir = project / "backend" / "app"
    app_dir.mkdir(parents=True)
    (project / "elsewhere").mkdir()
    config_path = app_dir / "config.py"
    shutil.copyfile(Path(__file__).resolve().parents[1] / "app" / "config.py", config_path)
    (project / ".env").write_text(
        "DATABASE_URL=sqlite:///shared.db\nMQ_ENABLED=true\n"
        "AGENT_MODE_ENABLED=true\nMODEL_ADAPTER_MODE=mock\n", encoding="utf-8")
    # A stale file must not become a second app-level configuration source.
    (project / "backend" / ".env").write_text(
        "DATABASE_URL=sqlite:///stale.db\n", encoding="utf-8")
    env = os.environ.copy()
    for key in ("DATABASE_URL", "MQ_ENABLED", "AGENT_MODE_ENABLED", "MODEL_ADAPTER_MODE", "PYTHON_DOTENV_DISABLED"):
        env.pop(key, None)
    if process_override:
        env["DATABASE_URL"] = "sqlite:///injected.db"
    code = (
        "import json, runpy, sys; c=runpy.run_path(sys.argv[1])['Config']; "
        "print(json.dumps([c.SQLALCHEMY_DATABASE_URI, c.MQ_ENABLED, "
        "c.AGENT_MODE_ENABLED, c.MODEL_ADAPTER_MODE]))"
    )
    result = subprocess.run([sys.executable, "-c", code, str(config_path)],
                            cwd=project / cwd_name, env=env, check=True,
                            capture_output=True, text=True)
    expected_db = "sqlite:///injected.db" if process_override else "sqlite:///shared.db"
    assert json.loads(result.stdout) == [expected_db, True, True, "mock"]
