"""Agent plan image jobs pin the interleaved-mode image count to n (real-provider E2E F2)."""
import pytest

from app.adapters.dashscope_image import DashScopeImageAdapter
from app.plans import runtime
from app.services.job_run_service import JobRunService
from tests.test_v4_execution import drain_plan, image_node, setup

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_V3_ENABLED=True, T2V_ENABLED=True)


@pytest.mark.parametrize("mq", [False, True])
def test_agent_plan_image_payload_pins_max_images_without_changing_approval(app_ctx, monkeypatch, mq):
    seen = []
    original = DashScopeImageAdapter.build_payload

    def capture(self, inputs, params):
        seen.append(dict(params))
        return original(self, inputs, params)

    monkeypatch.setattr(DashScopeImageAdapter, "build_payload", capture)
    run, version, registry = setup([image_node()])
    app_ctx.config.update(MQ_ENABLED=mq, MQ_WORKER_ACTIVE=mq)
    if not mq:
        monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    runtime.begin(run, version, registry=registry)
    assert drain_plan(run, registry, mq=mq) == "awaiting_result_review"
    assert seen and all(params["max_images"] == 1 and params["enable_interleave"] is True for params in seen)
    # The approval-bound task params are unchanged; only the provider payload differs.
    assert not {"enable_interleave", "max_images"} & set(runtime.latest_tasks(run)["image"].inputs["params"])


def test_classic_payload_keeps_the_catalog_default(app_ctx):
    payload = DashScopeImageAdapter(model=None).build_payload({"prompt": "cat"}, {"n": 1, "enable_interleave": True})
    assert payload["parameters"]["enable_interleave"] is True and "max_images" not in payload["parameters"]
