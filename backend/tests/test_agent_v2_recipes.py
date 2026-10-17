"""Duration allocation stays bounded for operator-owned capability catalogs."""

import pytest

from app.agent import recipes
from app.agent.model_selection import validate_generation_model
from app.api import AppError
from app.services.model_service import ModelService


def configure(*, low=1, high=15, step=1, provider_type="integer", enum=None):
    model = ModelService.get_model("wan2.7-i2v")
    model.capabilities = {**model.capabilities, "duration": {"min": low, "max": high, "step": step}}
    duration = {**model.parameter_schema["duration"], "type": provider_type}
    if enum is not None:
        duration["enum"] = enum
    model.parameter_schema = {**model.parameter_schema, "duration": duration}
    return model


def test_two_minute_story_remains_balanced(app_ctx):
    durations = recipes.distribute_duration(120, 8, configure())
    assert durations == [15] * 8
    assert sum(durations) == 120


@pytest.mark.parametrize("step", [-1, 0, float("inf")])
def test_nonpositive_or_nonfinite_steps_are_rejected_before_allocation(app_ctx, step):
    model = configure(step=step)
    with pytest.raises(AppError) as stopped:
        recipes.distribute_duration(120, 8, model)
    assert stopped.value.code == "MODEL_CAPABILITY_MISMATCH"
    with pytest.raises(AppError) as shared:
        validate_generation_model(model, "i2v", {"duration": 5}, reference_count=1)
    assert shared.value.code == "MODEL_CAPABILITY_MISMATCH"


@pytest.mark.parametrize("step", [1e-12, 1e-40])
def test_fine_grid_is_computed_without_enumeration_or_decimal_precision_failure(app_ctx, monkeypatch, step):
    model = configure(step=step)
    checked = []
    original = recipes.validate_generation_model

    def record(*args, **kwargs):
        checked.append(args[2]["duration"])
        return original(*args, **kwargs)

    monkeypatch.setattr(recipes, "validate_generation_model", record)
    durations = recipes.distribute_duration(120, 8, model)
    assert durations == [15] * 8
    assert checked == [15]
    assert validate_generation_model(model, "i2v", {"duration": 5}, reference_count=1)["duration"] == 5


def test_integer_provider_intersects_fractional_capability_grid(app_ctx):
    durations = recipes.distribute_duration(13, 3, configure(low=1.5, step=0.5))
    assert durations == [4, 4, 5]
    assert all(type(value) is int for value in durations)
    with pytest.raises(AppError) as stopped:
        recipes.distribute_duration(13, 3, configure(low=1.1, step=0.2))
    assert stopped.value.code == "MODEL_CAPABILITY_MISMATCH"


def test_provider_enum_is_filtered_by_capability_grid(app_ctx):
    durations = recipes.distribute_duration(18, 2, configure(step=2, enum=[3, 6, 9, 12]))
    assert durations == [9, 9]
    with pytest.raises(AppError):
        recipes.distribute_duration(18, 2, configure(step=2, enum=[6, 12]))


def test_numeric_provider_preserves_fine_fractional_duration_grid(app_ctx):
    model = configure(step=1e-12, provider_type="number")
    durations = recipes.distribute_duration(10, 3, model)
    assert sum(durations) == pytest.approx(10)
    assert max(durations) - min(durations) == pytest.approx(1e-12, abs=1e-15)
    assert all(validate_generation_model(model, "i2v", {"duration": value}, reference_count=1) for value in durations)
