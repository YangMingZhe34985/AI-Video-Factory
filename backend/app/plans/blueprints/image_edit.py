"""Author an image edit with explicit owned-image references."""
from pydantic import Field, model_validator
from app.agent.request_spec import StrictModel
from app.plans.blueprints.common import SimpleDraft, build_simple


class Params(StrictModel):
    plan: SimpleDraft
    goal: str | None = Field(default=None, min_length=1, max_length=2000)

    @model_validator(mode="after")
    def correct_recipe(self):
        if self.plan.recipe != "image_edit":
            raise ValueError("image-edit requires an image_edit plan")
        return self


def build(params, *, run, caller_agent="director"):
    return build_simple(Params.model_validate(params), "image-edit", run, caller_agent)
