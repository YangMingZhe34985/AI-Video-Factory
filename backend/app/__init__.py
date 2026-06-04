import os

import click
from flask import Flask
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from sqlalchemy import inspect

from app.api import register_auth_handlers, register_blueprints, register_error_handlers
from app.config import config_by_name
from app.extensions import db, migrate
from app.services.model_service import ModelService
from app.services.schema_service import SchemaService
from app.services.storage_service import StorageService


def create_app(config_name: str | None = None) -> Flask:
    app = Flask(__name__)
    selected = config_name or os.getenv("FLASK_ENV", "development")
    app.config.from_object(config_by_name.get(selected, config_by_name["development"]))

    StorageService.ensure_storage_dirs(app.config)

    db.init_app(app)
    migrate.init_app(app, db)
    jwt = JWTManager(app)
    CORS(app, supports_credentials=True)

    from app import models  # noqa: F401

    if app.config.get("AUTO_REPAIR_SCHEMA", True):
        with app.app_context():
            try:
                repaired = SchemaService.ensure_compatible_schema()
                if repaired:
                    app.logger.info("Schema compatibility repairs applied: %s", ", ".join(repaired))
                inspector = inspect(db.engine)
                if inspector.has_table("series"):
                    from app.services.series_service import SeriesService
                    SeriesService.ensure_default_series()
                if inspector.has_table("models"):
                    ModelService.seed_defaults()
                if inspector.has_table("workflow_nodes"):
                    from app.services.workflow_service import WorkflowService

                    WorkflowService.seed_default_nodes()
            except Exception as exc:
                app.logger.warning("Schema compatibility check skipped: %s", exc)

    register_blueprints(app)
    register_auth_handlers(app, jwt)
    register_error_handlers(app)
    register_cli(app)
    return app


def register_cli(app: Flask) -> None:
    def seed_default_data() -> dict:
        from app.models.template import Template
        from app.services.prompt_service import PromptService
        from app.services.series_service import SeriesService
        from app.services.workflow_service import WorkflowService

        SeriesService.ensure_default_series()
        template_created = 0
        if not Template.query.filter_by(template_id="default").first():
            PromptService.create_template(
                {
                    "template_id": "default",
                    "name": "Default Template",
                    "series": "default",
                    "description": "Default template seeded for new workflow jobs.",
                    "config": {},
                }
            )
            template_created = 1
        models_created = ModelService.seed_defaults()
        nodes_created = WorkflowService.seed_default_nodes()
        return {
            "templates": template_created,
            "models": models_created,
            "workflow_nodes": nodes_created,
        }

    @app.cli.command("init-db")
    def init_db_command():
        # Alembic `db upgrade` is the recommended schema path. create_all is
        # kept as a compatibility no-op/fallback for older local MVP setups.
        db.create_all()
        SchemaService.ensure_compatible_schema()
        seeded = seed_default_data()
        print(
            "Database initialized and default data seeded. "
            f"templates={seeded['templates']}, "
            f"models={seeded['models']}, "
            f"workflow_nodes={seeded['workflow_nodes']}"
        )

    @app.cli.command("repair-schema")
    def repair_schema_command():
        repaired = SchemaService.ensure_compatible_schema()
        if repaired:
            print(f"Schema repaired: {', '.join(repaired)}")
        else:
            print("Schema already compatible.")

    @app.cli.command("seed-defaults")
    def seed_defaults_command():
        seeded = seed_default_data()
        print(
            "Seeded defaults. "
            f"templates={seeded['templates']}, "
            f"models={seeded['models']}, "
            f"workflow_nodes={seeded['workflow_nodes']}"
        )

    @app.cli.command("seed-factory-prompts")
    @click.argument("template_id")
    @click.option("--overwrite", is_flag=True, help="Create new prompt versions even when prompt types exist.")
    def seed_factory_prompts_command(template_id: str, overwrite: bool):
        from app.services.prompt_service import PromptService

        prompts = PromptService.seed_factory_prompts(
            template_id, skip_existing=not overwrite
        )
        print(f"Seeded factory prompts. template_id={template_id}, created={len(prompts)}")
