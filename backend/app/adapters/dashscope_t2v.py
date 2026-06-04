from app.adapters.dashscope_common import DashScopeGenerationAdapter


class DashScopeT2VAdapter(DashScopeGenerationAdapter):
    """DashScope text-to-video adapter shell."""

    provider_name = "dashscope"
    task_type = "text_to_video"
    output_kind = "video"

    def create_url(self) -> str:
        return f"{self.dashscope_base_url()}/services/aigc/video-generation/video-synthesis"

    def build_payload(self, inputs: dict, params: dict) -> dict:
        self.validate_inputs(inputs, params)
        input_obj = {"prompt": inputs["prompt"]}
        if inputs.get("negative_prompt"):
            input_obj["negative_prompt"] = inputs["negative_prompt"]
        if inputs.get("audio_input"):
            input_obj["audio_url"] = self.upload_local_file_get_oss_url(
                self.model_id, inputs["audio_input"]
            )
        parameters = {
            "resolution": params.get("resolution", "720P"),
            "ratio": params.get("ratio", "9:16"),
            "duration": int(params.get("duration", 5)),
            "prompt_extend": bool(params.get("prompt_extend", False)),
            "watermark": bool(params.get("watermark", False)),
        }
        if params.get("seed") is not None:
            parameters["seed"] = int(params["seed"])
        return {"model": self.model_id, "input": input_obj, "parameters": parameters}
