"""Plan tasks have identical migrated and create_all schemas."""
from flask_migrate import downgrade, upgrade
from sqlalchemy import inspect

from app.extensions import db
from app.models import PlanNodeTask
from app.services.schema_service import SchemaService
from tests.test_migrations import MIGRATIONS_DIR, _empty_app, _version


def test_plan_node_migration_matches_model_and_can_downgrade(tmp_path):
    app = _empty_app(tmp_path)
    with app.app_context():
        upgrade(directory=MIGRATIONS_DIR)
        assert _version() == "20261019_005"
        inspector = inspect(db.engine)
        assert {item["name"] for item in inspector.get_columns("plan_node_tasks")} == set(PlanNodeTask.__table__.columns.keys())
        assert {tuple(item["column_names"]) for item in inspector.get_unique_constraints("plan_node_tasks")} == {
            ("run_id", "plan_version", "node_id", "attempt")}
        downgrade(directory=MIGRATIONS_DIR, revision="20261018_004")
        assert not inspect(db.engine).has_table("plan_node_tasks")
        assert inspect(db.engine).has_table("agent_plan_versions")
        upgrade(directory=MIGRATIONS_DIR)
        assert _version() == "20261019_005"
        db.engine.dispose()


def test_plan_node_schema_repair_is_idempotent(tmp_path):
    app = _empty_app(tmp_path)
    with app.app_context():
        upgrade(directory=MIGRATIONS_DIR, revision="20261018_004")
        assert "plan_node_tasks" in SchemaService.ensure_compatible_schema()
        assert "plan_node_tasks" not in SchemaService.ensure_compatible_schema()
        db.session.remove()
        upgrade(directory=MIGRATIONS_DIR)
        assert _version() == "20261019_005"
        db.engine.dispose()
