import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _path_env(name: str, default: str) -> str:
    raw = os.getenv(name, default)
    path = Path(raw)
    if not path.is_absolute():
        path = BASE_DIR / path
    return str(path)


def _database_engine_options(uri: str) -> dict:
    if not uri.startswith("mysql"):
        return {}
    return {
        "pool_pre_ping": _bool_env("DATABASE_POOL_PRE_PING", True),
        "pool_recycle": int(os.getenv("DATABASE_POOL_RECYCLE_SEC", "300")),
        "pool_timeout": int(os.getenv("DATABASE_POOL_TIMEOUT_SEC", "30")),
        "pool_size": int(os.getenv("DATABASE_POOL_SIZE", "5")),
        "max_overflow": int(os.getenv("DATABASE_MAX_OVERFLOW", "10")),
        "connect_args": {
            "connect_timeout": int(os.getenv("DATABASE_CONNECT_TIMEOUT_SEC", "10")),
            "read_timeout": int(os.getenv("DATABASE_READ_TIMEOUT_SEC", "120")),
            "write_timeout": int(os.getenv("DATABASE_WRITE_TIMEOUT_SEC", "120")),
        },
    }


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", os.getenv("SECRET_KEY", "change-me"))
    JWT_ACCESS_TOKEN_EXPIRES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRES", "3600"))
    JWT_REFRESH_TOKEN_EXPIRES = int(os.getenv("JWT_REFRESH_TOKEN_EXPIRES", "2592000"))
    API_AUTH_REQUIRED = _bool_env("API_AUTH_REQUIRED", True)
    AUTO_REPAIR_SCHEMA = _bool_env("AUTO_REPAIR_SCHEMA", True)
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        f"sqlite:///{BASE_DIR / 'storage' / 'video_factory.db'}",
    )
    SQLALCHEMY_ENGINE_OPTIONS = _database_engine_options(SQLALCHEMY_DATABASE_URI)
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    STORAGE_ROOT = _path_env("STORAGE_ROOT", "storage")
    UPLOAD_FOLDER = _path_env("UPLOAD_FOLDER", "storage/uploads")
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH_MB", "500")) * 1024 * 1024

    DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
    DASHSCOPE_API_BASE_URL = os.getenv(
        "DASHSCOPE_API_BASE_URL",
        os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/api/v1"),
    )
    DASHSCOPE_OPENAI_BASE_URL = os.getenv(
        "DASHSCOPE_OPENAI_BASE_URL",
        os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    )
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_OPENAI_BASE_URL = os.getenv(
        "DEEPSEEK_OPENAI_BASE_URL",
        "https://api.deepseek.com/v1",
    )
    MODEL_ADAPTER_MODE = os.getenv("MODEL_ADAPTER_MODE", "auto")
    REQUEST_TIMEOUT_SEC = int(os.getenv("REQUEST_TIMEOUT_SEC", "120"))
    DOWNLOAD_TIMEOUT_SEC = int(os.getenv("DOWNLOAD_TIMEOUT_SEC", "600"))
    POLL_INTERVAL_SEC = int(os.getenv("POLL_INTERVAL_SEC", "10"))
    MAX_POLL_ROUNDS = int(os.getenv("MAX_POLL_ROUNDS", "90"))
    VIDEO_COMPRESSION_ENABLED = _bool_env("VIDEO_COMPRESSION_ENABLED", True)
    VIDEO_COMPRESSION_CRF = os.getenv("VIDEO_COMPRESSION_CRF", "28")
    VIDEO_COMPRESSION_PRESET = os.getenv("VIDEO_COMPRESSION_PRESET", "medium")
    VIDEO_COMPRESSION_AUDIO_BITRATE = os.getenv("VIDEO_COMPRESSION_AUDIO_BITRATE", "128k")
    FFMPEG_BINARY = os.getenv("FFMPEG_BINARY", "")
    FACTORY_PROMPTS_DIR = _path_env(
        "FACTORY_PROMPTS_DIR", str(BASE_DIR.parent / "factory_prompts")
    )
    FAILURE_AGENT_ON_ERROR = _bool_env("FAILURE_AGENT_ON_ERROR", True)
    FAILURE_AGENT_ENABLED = _bool_env("FAILURE_AGENT_ENABLED", FAILURE_AGENT_ON_ERROR)
    FAILURE_AGENT_MAX_RETRIES = min(
        2, max(0, int(os.getenv("FAILURE_AGENT_MAX_RETRIES", "1")))
    )

    DEFAULT_VIDEO_UNDERSTANDING_MODEL = os.getenv(
        "DEFAULT_VIDEO_UNDERSTANDING_MODEL", "qwen3.7-plus"
    )
    DEFAULT_PROMPT_REWRITE_MODEL = os.getenv(
        "DEFAULT_PROMPT_REWRITE_MODEL", "deepseek-v4-flash"
    )
    DEFAULT_T2V_MODEL = os.getenv("DEFAULT_T2V_MODEL", "wan2.7-t2v")
    DEFAULT_IMAGE_MODEL = os.getenv("DEFAULT_IMAGE_MODEL", "wan2.6-image")
    DEFAULT_R2V_FLASH_MODEL = os.getenv(
        "DEFAULT_R2V_FLASH_MODEL", "wan2.6-r2v-flash"
    )
    DEFAULT_I2V_MODEL = os.getenv("DEFAULT_I2V_MODEL", "wan2.7-i2v")
    DEFAULT_I2I_TEST_I2V_MODEL = os.getenv(
        "DEFAULT_I2I_TEST_I2V_MODEL", "wan2.6-i2v-flash"
    )
    DEFAULT_I2I_TEST_IMAGE_MODEL = os.getenv(
        "DEFAULT_I2I_TEST_IMAGE_MODEL", "wan2.7-image"
    )
    DEFAULT_NEGATIVE_PROMPT = os.getenv(
        "DEFAULT_NEGATIVE_PROMPT",
        "主角动作卡顿，神情僵硬，面部变形，手臂错位，"
        "手指畸形，肢体扭曲，身体比例错误，多手，多脚，塑料感服饰",
    )
    I2I_TEST_MALE_DATASET_DIR = os.getenv(
        "I2I_TEST_MALE_DATASET_DIR", "workspace/personas/male"
    )
    I2I_TEST_FEMALE_DATASET_DIR = os.getenv(
        "I2I_TEST_FEMALE_DATASET_DIR", "workspace/personas/female"
    )
    R2V_REFERENCE_IMAGE_DIRS = os.getenv(
        "R2V_REFERENCE_IMAGE_DIRS",
        "workspace/personas/male,workspace/personas/female",
    )

    T2V_ENABLED = _bool_env("T2V_ENABLED", False)
    FIRST_FRAME_IMAGE_ENABLED = _bool_env("FIRST_FRAME_IMAGE_ENABLED", True)
    I2V_ENABLED = _bool_env("I2V_ENABLED", True)
    R2V_FLASH_ENABLED = _bool_env("R2V_FLASH_ENABLED", False)
    I2I_TEST_ENABLED = _bool_env("I2I_TEST_ENABLED", False)
    WORKFLOW_PARALLEL_ENABLED = _bool_env("WORKFLOW_PARALLEL_ENABLED", True)
    WORKFLOW_MAX_PARALLEL_NODES = int(os.getenv("WORKFLOW_MAX_PARALLEL_NODES", "4"))
    WORKFLOW_MAX_PARALLEL_POLLS = int(os.getenv("WORKFLOW_MAX_PARALLEL_POLLS", "2"))
    JOB_QUEUE_ENABLED = _bool_env("JOB_QUEUE_ENABLED", True)
    JOB_MAX_CONCURRENT_RUNS = int(os.getenv("JOB_MAX_CONCURRENT_RUNS", "2"))
    JOB_QUEUE_POLL_INTERVAL_SEC = int(os.getenv("JOB_QUEUE_POLL_INTERVAL_SEC", "1"))

    DEFAULT_WORKFLOW_NODES = [
        {
            "node_key": "reverse_prompts",
            "display_name": "Reverse Prompts to T2V",
            "sequence": 10,
            "branch_key": "core",
            "enabled": True,
            "depends_on": [],
        },
        {
            "node_key": "submit_t2v",
            "display_name": "Submit T2V",
            "sequence": 20,
            "branch_key": "t2v",
            "enabled": T2V_ENABLED,
            "depends_on": ["reverse_prompts"],
        },
        {
            "node_key": "poll_t2v",
            "display_name": "Poll T2V",
            "sequence": 30,
            "branch_key": "t2v",
            "enabled": T2V_ENABLED,
            "depends_on": ["submit_t2v"],
        },
        {
            "node_key": "rewrite_prompts",
            "display_name": "Rewrite T2V to First Frame/I2V",
            "sequence": 40,
            "branch_key": "core",
            "enabled": True,
            "depends_on": ["reverse_prompts"],
        },
        {
            "node_key": "submit_first_frame_image",
            "display_name": "Submit First Frame Image",
            "sequence": 50,
            "branch_key": "first_frame_image",
            "enabled": FIRST_FRAME_IMAGE_ENABLED,
            "depends_on": ["rewrite_prompts"],
        },
        {
            "node_key": "poll_first_frame_image",
            "display_name": "Poll First Frame Image",
            "sequence": 60,
            "branch_key": "first_frame_image",
            "enabled": FIRST_FRAME_IMAGE_ENABLED,
            "depends_on": ["submit_first_frame_image"],
        },
        {
            "node_key": "rewrite_t2i_to_i2i",
            "display_name": "Rewrite T2I to I2I",
            "sequence": 65,
            "branch_key": "i2i_test",
            "enabled": I2I_TEST_ENABLED,
            "depends_on": ["rewrite_prompts"],
        },
        {
            "node_key": "prepare_i2i_test_batch",
            "display_name": "Prepare I2I Test Batch",
            "sequence": 66,
            "branch_key": "i2i_test",
            "enabled": I2I_TEST_ENABLED,
            "depends_on": ["rewrite_t2i_to_i2i"],
        },
        {
            "node_key": "submit_i2i_test_i2v",
            "display_name": "Submit I2I Test I2V",
            "sequence": 69,
            "branch_key": "i2i_test",
            "enabled": I2I_TEST_ENABLED,
            "depends_on": ["poll_i2i_test_image"],
        },
        {
            "node_key": "poll_i2i_test_i2v",
            "display_name": "Poll I2I Test I2V",
            "sequence": 70,
            "branch_key": "i2i_test",
            "enabled": I2I_TEST_ENABLED,
            "depends_on": ["submit_i2i_test_i2v"],
        },
        {
            "node_key": "submit_i2i_test_image",
            "display_name": "Submit I2I Test Image",
            "sequence": 67,
            "branch_key": "i2i_test",
            "enabled": I2I_TEST_ENABLED,
            "depends_on": ["prepare_i2i_test_batch"],
        },
        {
            "node_key": "poll_i2i_test_image",
            "display_name": "Poll I2I Test Image",
            "sequence": 68,
            "branch_key": "i2i_test",
            "enabled": I2I_TEST_ENABLED,
            "depends_on": ["submit_i2i_test_image"],
        },
        {
            "node_key": "submit_i2v",
            "display_name": "Submit Main I2V",
            "sequence": 80,
            "branch_key": "i2v",
            "enabled": I2V_ENABLED,
            "depends_on": ["rewrite_prompts", "poll_first_frame_image"],
        },
        {
            "node_key": "poll_i2v",
            "display_name": "Poll Main I2V",
            "sequence": 90,
            "branch_key": "i2v",
            "enabled": I2V_ENABLED,
            "depends_on": ["submit_i2v"],
        },
        {
            "node_key": "reverse_prompts4r2v",
            "display_name": "Rewrite T2V to R2V",
            "sequence": 110,
            "branch_key": "r2v_flash",
            "enabled": R2V_FLASH_ENABLED,
            "depends_on": ["reverse_prompts"],
        },
        {
            "node_key": "submit_r2v_flash",
            "display_name": "Submit R2V Flash",
            "sequence": 120,
            "branch_key": "r2v_flash",
            "enabled": R2V_FLASH_ENABLED,
            "depends_on": ["reverse_prompts4r2v"],
        },
        {
            "node_key": "poll_r2v_flash",
            "display_name": "Poll R2V",
            "sequence": 130,
            "branch_key": "r2v_flash",
            "enabled": R2V_FLASH_ENABLED,
            "depends_on": ["submit_r2v_flash"],
        },
        {
            "node_key": "failure_agent",
            "display_name": "Failure Agent",
            "sequence": 980,
            "branch_key": "core",
            "enabled": False,
            "depends_on": [],
        },
        {
            "node_key": "export_manifest",
            "display_name": "Export Manifest",
            "sequence": 990,
            "branch_key": "core",
            "enabled": True,
            "depends_on": ["poll_i2v", "poll_i2i_test_i2v", "poll_t2v", "poll_r2v_flash"],
        },
    ]


class DevelopmentConfig(Config):
    DEBUG = True


class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"


class ProductionConfig(Config):
    DEBUG = False


config_by_name = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
