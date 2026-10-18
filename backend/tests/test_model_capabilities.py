from flask_migrate import downgrade, upgrade
from sqlalchemy import inspect, text

from app.extensions import db
from app.models import ModelRegistry
from app.services.model_service import DEFAULT_MODELS, ModelService
from app.services.schema_service import SchemaService
from tests.test_migrations import MIGRATIONS_DIR, _empty_app


def test_seeds_complete_and_preserve_operator_values(app_ctx):
    expected = {"modes", "duration", "resolutions", "aspect_ratios", "reference_images",
                "pricing", "quality_tier", "agent_selectable", "notes"}
    for seed in DEFAULT_MODELS:
        model = ModelService.get_model(seed["model_id"])
        assert expected <= set(model.capabilities)
        assert model.capabilities["modes"]
        assert "演示" in model.capabilities["notes"]
        if set(model.capabilities["modes"]) & {"i2i", "i2v", "r2v", "image_understanding"}:
            assert model.capabilities["reference_images"]["max"] >= 1
        if model.capabilities["pricing"]["unit"] == "second":
            assert model.capabilities["duration"]["min"] <= model.default_params["duration"]
            assert model.capabilities["duration"]["max"] >= model.default_params["duration"]
    model = ModelService.get_model("wan2.7-i2v")
    model.capabilities = {**model.capabilities, "pricing": {"unit": "second", "credits_per_unit": 3.25},
                          "agent_selectable": False}
    db.session.commit()
    assert ModelService.seed_defaults() == 0
    assert model.capabilities["pricing"]["credits_per_unit"] == 3.25
    assert model.capabilities["agent_selectable"] is False


def test_legacy_empty_capabilities_are_backfilled(app_ctx):
    model = ModelService.get_model("wan2.7-image")
    model.capabilities = {}
    db.session.commit()
    ModelService.seed_defaults()
    assert model.task_type == "text_to_image"
    assert model.capabilities["modes"] == ["t2i", "i2i"]


def test_registry_api_round_trips_capabilities(client):
    payload = {"model_id": "custom-video", "display_name": "Custom Video", "provider": "mock",
               "task_type": "image_to_video", "adapter_name": "dashscope_i2v",
               "capabilities": {"modes": ["i2v"], "agent_selectable": False}}
    result = client.post("/api/models", json=payload)
    assert result.status_code == 201
    assert result.json["data"]["capabilities"] == payload["capabilities"]
    updated = client.put("/api/models/custom-video", json={"capabilities": {"modes": ["i2v"], "agent_selectable": True}})
    assert updated.status_code == 200
    assert updated.json["data"]["capabilities"]["agent_selectable"] is True
    assert client.get("/api/models/custom-video").json["data"]["task_type"] == "image_to_video"


def test_migration_and_schema_repair_are_repeatable(tmp_path):
    app = _empty_app(tmp_path)
    with app.app_context():
        upgrade(directory=MIGRATIONS_DIR)
        downgrade(directory=MIGRATIONS_DIR, revision="20261017_001")
        # Simulate a real pre-capabilities row and verify non-null backfill.
        db.session.execute(text("INSERT INTO models (model_id, display_name, provider, task_type, adapter_name, enabled, input_schema, parameter_schema, output_schema, default_params, created_at, updated_at) VALUES ('legacy', 'Legacy', 'mock', 'text_to_text', 'qwen_chat', 1, '{}', '{}', '{}', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
        db.session.commit()
        upgrade(directory=MIGRATIONS_DIR)
        upgrade(directory=MIGRATIONS_DIR)
        assert ModelRegistry.query.filter_by(model_id="legacy").one().capabilities == {}
        column = next(c for c in inspect(db.engine).get_columns("models") if c["name"] == "capabilities")
        assert column["nullable"] is False
        db.session.remove()
        downgrade(directory=MIGRATIONS_DIR, revision="20261017_001")
        assert "models.capabilities" in SchemaService.ensure_compatible_schema()
        assert "models.capabilities" not in SchemaService.ensure_compatible_schema()
        db.session.remove()
        upgrade(directory=MIGRATIONS_DIR)
        db.session.remove()
        db.engine.dispose()
        assert not app.logger.disabled  # Migrations must preserve cost/operational warnings.
