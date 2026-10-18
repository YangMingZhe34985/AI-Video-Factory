"""Author the v2 text-to-image route without generating or charging."""
from pydantic import Field, model_validator
from app.agent.request_spec import StrictModel
from app.plans.blueprints.common import SimpleDraft, build_simple


class Params(StrictModel):
    plan: SimpleDraft
    goal: str | None = Field(default=None, min_length=1, max_length=2000)

    @model_validator(mode="after")
    def correct_recipe(self):
        if self.plan.recipe != "image_create" or self.plan.image.mode != "t2i":
            raise ValueError("image-create requires an image_create t2i plan")
        return self


def build(params, *, run, caller_agent="director"):
    return build_simple(Params.model_validate(params), "image-create", run, caller_agent)
