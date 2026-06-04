from app.adapters.dashscope_common import DashScopeGenerationAdapter


class DashScopeImageAdapter(DashScopeGenerationAdapter):
    """DashScope image generation adapter shell."""

    provider_name = "dashscope"
    task_type = "text_to_image"
    output_kind = "image"

    def create_url(self) -> str:
        return f"{self.dashscope_base_url()}/services/aigc/image-generation/generation"

    def build_payload(self, inputs: dict, params: dict) -> dict:
        self.validate_inputs(inputs, params)
        content = []
        if inputs.get("source_image"):
            image_value = inputs["source_image"]
            image_url = (
                image_value
                if self.use_mock or self.is_remote_resource(str(image_value))
                else self.upload_local_file_get_oss_url(self.model_id, image_value)
            )
            content.append({"image": image_url})
        content.append({"text": inputs["prompt"]})
        parameters = {
            "prompt_extend": bool(params.get("prompt_extend", True)),
            "watermark": bool(params.get("watermark", False)),
            "n": int(params.get("n", 1)),
            "enable_interleave": bool(params.get("enable_interleave", True)),
            "size": params.get("size", "1280*1280"),
        }
        if inputs.get("negative_prompt"):
            parameters["negative_prompt"] = inputs["negative_prompt"]
        return {
            "model": self.model_id,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": content,
                    }
                ]
            },
            "parameters": parameters,
        }
