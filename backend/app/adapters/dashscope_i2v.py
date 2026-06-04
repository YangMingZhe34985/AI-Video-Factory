from app.adapters.dashscope_common import DashScopeGenerationAdapter


class DashScopeI2VAdapter(DashScopeGenerationAdapter):
    """DashScope image-to-video adapter shell."""

    provider_name = "dashscope"
    task_type = "image_to_video"
    output_kind = "video"

    def create_url(self) -> str:
        return f"{self.dashscope_base_url()}/services/aigc/video-generation/video-synthesis"

    def build_payload(self, inputs: dict, params: dict) -> dict:
        self.validate_inputs(inputs, params)
        image_value = inputs["first_frame_image"]
        image_url = (
            image_value
            if self.use_mock or self.is_remote_resource(str(image_value))
            else self.upload_local_file_get_oss_url(self.model_id, image_value)
        )
        if self.model_id.startswith("wan2.6-i2v"):
            input_obj = {"prompt": inputs["prompt"], "img_url": image_url}
            parameters = {
                "resolution": params.get("resolution", "720P"),
                "prompt_extend": bool(params.get("prompt_extend", True)),
                "duration": int(params.get("duration", 10)),
            }
            if params.get("shot_type"):
                parameters["shot_type"] = params["shot_type"]
            if params.get("audio") is not None:
                parameters["audio"] = bool(params["audio"])
            return {"model": self.model_id, "input": input_obj, "parameters": parameters}

        media = [{"type": "first_frame", "url": image_url}]
        if self.model_id.startswith("happyhorse-"):
            parameters = {
                "resolution": params.get("resolution", "1080P"),
                "duration": int(params.get("duration", 5)),
                "watermark": bool(params.get("watermark", False)),
            }
            if params.get("seed") is not None:
                parameters["seed"] = int(params["seed"])
            return {
                "model": self.model_id,
                "input": {"prompt": inputs["prompt"], "media": media},
                "parameters": parameters,
            }

        if inputs.get("driving_audio"):
            media.append(
                {
                    "type": "driving_audio",
                    "url": self.upload_local_file_get_oss_url(
                        self.model_id, inputs["driving_audio"]
                    ),
                }
            )
        return {
            "model": self.model_id,
            "input": {"prompt": inputs["prompt"], "media": media},
            "parameters": {
                "resolution": params.get("resolution", "720P"),
                "duration": int(params.get("duration", 10)),
                "prompt_extend": bool(params.get("prompt_extend", False)),
                "watermark": bool(params.get("watermark", False)),
            },
        }
