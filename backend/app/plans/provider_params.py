"""Provider payload adjustments for Agent plan jobs that are not part of approval.

Approval binds the plan's params exactly; validation always uses those. This
module only adds provider switches that make the payload honour what was
approved, for both the synchronous runner and the MQ submit consumer.
"""


def provider_params(job, adapter_name, params):
    config = (job.config or {}) if job is not None else {}
    if adapter_name == "dashscope_image" and (config.get("agent_plan") or config.get("agent_plan_preview")):
        # wan2.6-image text-to-image runs in interleaved mode, where n is ignored and
        # max_images (default 5) sets the count: an approved n=1 node received five
        # billed images and failed its output count (D-062). Pin max_images to n.
        return {**params, "enable_interleave": True, "max_images": int(params.get("n", 1))}
    return params
