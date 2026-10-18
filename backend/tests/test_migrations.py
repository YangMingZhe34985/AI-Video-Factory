"""Schema paths for the tool_invocations ledger."""

from flask_migrate import upgrade
from sqlalchemy import inspect, text

from app import create_app
from app.extensions import db
from app.services.schema_service import SchemaService
from tests.conftest import BACKEND_DIR

MIGRATIONS_DIR = str(BACKEND_DIR / "migrations")


def _empty_app(tmp_path):
    return create_app(
        "testing",
        config_overrides={
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{(tmp_path / 'migrate.db').as_posix()}",
            "SQLALCHEMY_ENGINE_OPTIONS": {},
            "STORAGE_ROOT": str(tmp_path / "storage"),
            "UPLOAD_FOLDER": str(tmp_path / "storage" / "uploads"),
            "AUTO_REPAIR_SCHEMA": False,
        },
    )


def _version():
    return db.session.execute(text("SELECT version_num FROM alembic_version")).scalar()


def test_alembic_upgrade_creates_ledger_table(tmp_path):
    app = _empty_app(tmp_path)
    with app.app_context():
        upgrade(directory=MIGRATIONS_DIR)

        inspector = inspect(db.engine)
        assert inspector.has_table("tool_invocations")
        columns = {column["name"] for column in inspector.get_columns("tool_invocations")}
        assert {"idempotency_key", "budget_scope", "job_id", "started_at", "estimated_cost"} <= columns
        assert inspector.has_table("agent_runs")
        assert inspector.has_table("job_dispatches")
        assert inspector.has_table("task_outbox")
        assert "operation_key" in {c["name"] for c in inspector.get_columns("api_tasks")}
        assert _version() == "20261018_002"
        db.engine.dispose()


def test_upgrade_tolerates_table_created_by_schema_repair(tmp_path):
    app = _empty_app(tmp_path)
    with app.app_context():
        upgrade(directory=MIGRATIONS_DIR, revision="20260603_001")
        # `flask db upgrade` boots the app first, so auto-repair may create the table.
        assert "tool_invocations" in SchemaService.ensure_compatible_schema()

        upgrade(directory=MIGRATIONS_DIR)

        assert inspect(db.engine).has_table("agent_runs")
        assert inspect(db.engine).has_table("task_outbox")
        assert _version() == "20261018_002"
        db.engine.dispose()


def test_schema_repair_adds_ledger_to_legacy_database(app_ctx):
    db.session.execute(text("DROP TABLE tool_invocations"))
    db.session.commit()

    assert "tool_invocations" in SchemaService.ensure_compatible_schema()
    assert inspect(db.engine).has_table("tool_invocations")
    assert "tool_invocations" not in SchemaService.ensure_compatible_schema()
