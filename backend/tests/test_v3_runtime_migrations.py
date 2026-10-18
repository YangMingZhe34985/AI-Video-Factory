"""V3 runtime tables support Alembic and create_all compatibility repair."""

from flask_migrate import downgrade, upgrade
from sqlalchemy import inspect, text

from app.extensions import db
from app.models import AgentDelegation, AgentStep, AgentWorkspaceItem
from app.services.schema_service import SchemaService
from tests.test_migrations import MIGRATIONS_DIR, _empty_app, _version

MODELS = (AgentDelegation, AgentStep, AgentWorkspaceItem)


def test_v3_alembic_tables_match_create_all_schema(tmp_path):
    app = _empty_app(tmp_path)
    with app.app_context():
        upgrade(directory=MIGRATIONS_DIR)
        inspector = inspect(db.engine)
        assert _version() == "20261018_004"
        for model in MODELS:
            columns = inspector.get_columns(model.__tablename__)
            assert {column["name"] for column in columns} == set(model.__table__.columns.keys())
            assert {tuple(item["column_names"]) for item in inspector.get_unique_constraints(model.__tablename__)} == {
                tuple(column.name for column in constraint.columns)
                for constraint in model.__table__.constraints if constraint.__class__.__name__ == "UniqueConstraint"}
        downgrade(directory=MIGRATIONS_DIR, revision="20261018_003")
        assert all(not inspect(db.engine).has_table(model.__tablename__) for model in MODELS)
        assert inspect(db.engine).has_table("tool_invocations")
        assert {"caller_agent", "delegation_id"} <= {
            column["name"] for column in inspect(db.engine).get_columns("tool_invocations")}
        upgrade(directory=MIGRATIONS_DIR)
        assert _version() == "20261018_004"
        db.engine.dispose()


def test_v3_schema_repair_and_migration_are_idempotent(tmp_path):
    app = _empty_app(tmp_path)
    with app.app_context():
        upgrade(directory=MIGRATIONS_DIR, revision="20261018_003")
        repaired = SchemaService.ensure_compatible_schema()
        assert {model.__tablename__ for model in MODELS} <= set(repaired)
        assert not {model.__tablename__ for model in MODELS} & set(SchemaService.ensure_compatible_schema())
        # App startup releases its scoped session before the Alembic CLI uses
        # another connection. End the simulated startup context's transaction.
        db.session.remove()
        upgrade(directory=MIGRATIONS_DIR)
        assert _version() == "20261018_004"
        db.engine.dispose()


def test_v3_create_all_database_can_repair_missing_runtime_tables(app_ctx):
    for model in reversed(MODELS):
        db.session.execute(text(f"DROP TABLE {model.__tablename__}"))
    db.session.commit()
    repaired = SchemaService.ensure_compatible_schema()
    assert {model.__tablename__ for model in MODELS} <= set(repaired)
    assert all(inspect(db.engine).has_table(model.__tablename__) for model in MODELS)
