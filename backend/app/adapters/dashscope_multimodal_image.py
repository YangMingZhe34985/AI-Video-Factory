from app.adapters.dashscope_common import DashScopeGenerationAdapter
from app.api import AppError

# Prefix that encodes a synchronous result URL inside the "task_id" field.
# poll() detects this prefix and returns success immediately without a network call.
_SYNC_PREFIX = "sync://"


class DashScopeMultimodalSyncAdapter(DashScopeGenerationAdapter):
    """
    Adapter for wan2.7-image (multimodal generation, synchronous).

    Why a separate adapter:
    - wan2.7-image belongs to the multimodal-generation family and must be called at
      /services/aigc/multimodal-generation/generation, NOT /image-generation/generation.
    - The multimodal endpoint returns the image synchronously; sending
      X-DashScope-Async would change the response shape unpredictably.
    - enable_interleave is omitted intentionally: it triggers stricter content-safety
      checks when a person reference image is present, causing random "输入/输出不合适"
      errors that do not appear with the same prompt in the standalone script.
    """

    provider_name = "dashscope"
    task_type = "multimodal_image"
    output_kind = "image"

    def create_url(self) -> str:
        return f"{self.dashscope_base_url()}/services/aigc/multimodal-generation/generation"

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
            "size": params.get("size", "1280*1280"),
            "n": int(params.get("n", 1)),
            "watermark": bool(params.get("watermark", False)),
        }

        return {
            "model": self.model_id,
            "input": {"messages": [{"role": "user", "content": content}]},
            "parameters": parameters,
        }

    def submit(self, payload: dict) -> dict:
        """Synchronous call — image URL is returned directly in the response."""
        if self.use_mock:
            return super().submit(payload)

        data = self.request_json(
            "POST",
            self.create_url(),
            headers={
                "Authorization": f"Bearer {self.api_key()}",
                "Content-Type": "application/json",
                "X-DashScope-OssResourceResolve": "enable",
                # No X-DashScope-Async — synchronous mode
            },
            json=payload,
        )

        image_url = self._extract_image_url(data)
        if not image_url:
            raise AppError(
                "API_TASK_FAILED",
                "Multimodal image generation returned no image URL",
                502,
                payload={"response": data},
            )

        # Encode the result URL as the provider_task_id so poll() can return
        # success immediately without a second network call.
        return {
            "provider_task_id": f"{_SYNC_PREFIX}{image_url}",
            "status": "submitted",
            "request_id": data.get("request_id"),
            "raw_response": data,
        }

    def poll(self, task_id: str) -> dict:
        """Sync result — extract the image URL from task_id and return success."""
        if self.use_mock:
            return super().poll(task_id)

        if str(task_id or "").startswith(_SYNC_PREFIX):
            image_url = task_id[len(_SYNC_PREFIX):]
            return {
                "provider_task_id": task_id,
                "status": "success",
                "vendor_status": "SUCCEEDED",
                "output_kind": "image",
                "result_url": image_url,
                "raw_response": {},
                "error_message": None,
            }

        # Fallback to async polling (e.g. if task_id comes from a previous run)
        return super().poll(task_id)
