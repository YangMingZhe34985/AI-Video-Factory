from app.adapters.dashscope_common import DashScopeGenerationAdapter


class DashScopeR2VFlashAdapter(DashScopeGenerationAdapter):
    """DashScope reference-to-video flash adapter shell."""

    provider_name = "dashscope"
    task_type = "reference_to_video"
    output_kind = "video"

    def create_url(self) -> str:
        return f"{self.dashscope_base_url()}/services/aigc/video-generation/video-synthesis"

    def build_payload(self, inputs: dict, params: dict) -> dict:
        self.validate_inputs(inputs, params)
        reference_images = inputs.get("reference_images") or []
        if not reference_images:
            raise ValueError("reference_images is required")
        reference_urls = [
            value
            if self.use_mock or self.is_remote_resource(str(value))
            else self.upload_local_file_get_oss_url(self.model_id, value)
            for value in reference_images
        ]
        if self.model_id.startswith("wan2.6-r2v"):
            parameters = {
                "size": params.get("size", "720*1280"),
                "duration": int(params.get("duration", 5)),
                "audio": bool(params.get("audio", False)),
                "shot_type": params.get("shot_type", "single"),
                "watermark": bool(params.get("watermark", False)),
            }
            if params.get("prompt_extend") is not None:
                parameters["prompt_extend"] = bool(params["prompt_extend"])
            return {
                "model": self.model_id,
                "input": {"prompt": inputs["prompt"], "reference_urls": reference_urls},
                "parameters": parameters,
            }
        return {
            "model": self.model_id,
            "input": {
                "prompt": inputs["prompt"],
                "media": [
                    {"type": "reference_image", "url": value}
                    for value in reference_urls
                ],
            },
            "parameters": {
                "resolution": params.get("resolution", "720P"),
                "ratio": params.get("ratio", "9:16"),
                "duration": int(params.get("duration", 5)),
                "prompt_extend": bool(params.get("prompt_extend", False)),
                "watermark": bool(params.get("watermark", False)),
            },
        }
