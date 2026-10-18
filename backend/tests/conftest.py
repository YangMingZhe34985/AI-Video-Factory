"""Shared fixtures for the classic-mode regression baseline.

Every test runs against an isolated SQLite file and storage root, with all
model adapters forced into mock mode and outbound HTTP blocked, so the suite
never touches a paid provider API.
"""

import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# app.config reads os.environ at import time and load_dotenv() never overrides
# variables that already exist, so this pins the test environment regardless
# of the developer's project-root .env.
os.environ.update(
    {
        "DATABASE_URL": "sqlite:///placeholder.db",
        "MODEL_ADAPTER_MODE": "mock",
        "DASHSCOPE_API_KEY": "",
        "DEEPSEEK_API_KEY": "",
        "OPENAI_API_KEY": "",
        "API_AUTH_REQUIRED": "false",
        "AUTO_REPAIR_SCHEMA": "true",
        "T2V_ENABLED": "false",
        "FIRST_FRAME_IMAGE_ENABLED": "true",
        "I2V_ENABLED": "true",
        "R2V_FLASH_ENABLED": "false",
        "I2I_TEST_ENABLED": "false",
        "WORKFLOW_PARALLEL_ENABLED": "true",
        "JOB_QUEUE_ENABLED": "false",
        # Offline legacy tests execute inline; MQ cases opt in explicitly and
        # drive their own consumers. Never inherit developer admission flags.
        "MQ_ENABLED": "false",
        "AGENT_MODE_ENABLED": "false",
        "AGENT_V3_ENABLED": "false",
        "AGENT_V3_DEFAULT_TEXT_MODEL": "deepseek-v4.1-flash",
        "AGENT_V3_DEFAULT_VISION_MODEL": "qwen3.7-plus",
        "AGENT_PRODUCER_MODEL": "",
        "AGENT_CRITIC_MODEL": "",
        "AGENT_REPAIR_MODEL": "",
        "AGENT_PLANNER_MODEL": "",
        "AGENT_VISION_MODEL": "",
        "AGENT_DIRECTOR_MODEL": "",
        "AGENT_RESEARCH_MODEL": "",
        "AGENT_ACCEPT_NEW_RUNS": "true",
        "AGENT_ALLOWED_USERS": "",
        "AGENT_STORY_V2_ENABLED": "false",
        "AGENT_STORY_PRODUCTION_ENABLED": "false",
        "AGENT_STORY_DELIVERY_ENABLED": "false",
        "AGENT_MAX_PARALLEL_SHOTS": "3",
        "AGENT_MAX_SHOT_AUTO_REPAIRS": "2",
        "AGENT_MAX_SHOT_REPAIR_CREDITS": "60",
        "AGENT_ENABLE_KEYFRAME_BRIDGE": "false",
        "AGENT_MAX_STORY_SHOTS": "30",
        "AGENT_STORY_DURATION_TOLERANCE_RATIO": "0.1",
        "AGENT_CREATIVE_MODEL": "",
        "AGENT_PROMPT_SMITH_MODEL": "",
        "AGENT_SEARCH_PROVIDER": "mock",
        "AGENT_SEARCH_TIMEOUT_SEC": "10",
        "AGENT_SEARCH_COST_PER_CALL": "0.2",
        "AGENT_FETCH_MAX_BYTES": "2000000",
        "AGENT_REFERENCE_MAX_MB": "10",
        "AGENT_RESEARCH_MAX_QUERIES": "6",
        "AGENT_RESEARCH_MAX_FETCHES": "6",
        "AGENT_MAX_REFERENCE_DOWNLOADS": "24",
        "FAILURE_AGENT_ON_ERROR": "false",
        "FAILURE_AGENT_ENABLED": "false",
        "FAILURE_AGENT_MAX_RETRIES": "1",
        "POLL_INTERVAL_SEC": "0",
        "MAX_POLL_ROUNDS": "3",
        "VIDEO_COMPRESSION_ENABLED": "false",
        "DEFAULT_VIDEO_UNDERSTANDING_MODEL": "qwen3.7-plus",
        "DEFAULT_PROMPT_REWRITE_MODEL": "deepseek-v4-flash",
        "DEFAULT_T2V_MODEL": "wan2.7-t2v",
        "DEFAULT_IMAGE_MODEL": "wan2.6-image",
        "DEFAULT_R2V_FLASH_MODEL": "wan2.6-r2v-flash",
        "DEFAULT_I2V_MODEL": "wan2.7-i2v",
        "DEFAULT_I2I_TEST_I2V_MODEL": "wan2.6-i2v-flash",
        "DEFAULT_I2I_TEST_IMAGE_MODEL": "wan2.7-image",
        "FACTORY_PROMPTS_DIR": str(REPO_ROOT / "factory_prompts"),
    }
)

import pytest  # noqa: E402
import requests  # noqa: E402
from urllib3.connection import HTTPConnection, HTTPSConnection  # noqa: E402

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.services.storage_service import MOCK_PNG_BYTES  # noqa: E402

from tests import helpers  # noqa: E402


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    def _blocked(self, request, **kwargs):
        raise RuntimeError(f"Outbound HTTP is blocked in tests: {request.method} {request.url}")

    monkeypatch.setattr(requests.Session, "send", _blocked)

    def _blocked_connection(_self):
        raise RuntimeError("Outbound urllib3 connections are blocked in tests")

    monkeypatch.setattr(HTTPConnection, "connect", _blocked_connection)
    monkeypatch.setattr(HTTPSConnection, "connect", _blocked_connection)


@pytest.fixture
def persona_dirs(tmp_path):
    root = tmp_path / "personas"
    dirs = {}
    for role in ("male", "female"):
        directory = root / role
        directory.mkdir(parents=True)
        for index in range(3):
            (directory / f"{role}_{index}.png").write_bytes(MOCK_PNG_BYTES)
        dirs[role] = directory
    return dirs


def _config_overrides(tmp_path: Path, persona_dirs: dict) -> dict:
    storage = tmp_path / "storage"
    return {
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        "SQLALCHEMY_ENGINE_OPTIONS": {"connect_args": {"timeout": 30}},
        "STORAGE_ROOT": str(storage),
        "UPLOAD_FOLDER": str(storage / "uploads"),
        "I2I_TEST_MALE_DATASET_DIR": str(persona_dirs["male"]),
        "I2I_TEST_FEMALE_DATASET_DIR": str(persona_dirs["female"]),
        "R2V_REFERENCE_IMAGE_DIRS": f"{persona_dirs['male']},{persona_dirs['female']}",
    }


@pytest.fixture
def app(tmp_path, persona_dirs, request):
    overrides = _config_overrides(tmp_path, persona_dirs)
    marker = request.node.get_closest_marker("config")
    if marker:
        overrides.update(marker.kwargs)
    flask_app = create_app("testing", config_overrides=overrides)
    result = flask_app.test_cli_runner().invoke(args=["init-db"])
    assert result.exit_code == 0, result.output
    yield flask_app
    with flask_app.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.fixture
def app_ctx(app):
    with app.app_context():
        yield app
        db.session.remove()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def source_video(tmp_path):
    path = tmp_path / "inputs" / "source.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fake mp4 bytes for regression tests\n")
    return path


@pytest.fixture
def h():
    return helpers


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "config(**overrides): extra Flask config overrides for the app fixture"
    )
