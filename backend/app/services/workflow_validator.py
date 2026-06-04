"""Workflow validation logic and node metadata definitions."""

INPUT_DEFINITIONS = {
    "source_video": {
        "label": "Source Video",
        "type": "video",
        "source_options": ["upload", "existing_artifact"],
        "artifact_type": "source_video",
    },
    "prompt:t2v": {
        "label": "T2V Prompt",
        "type": "textarea",
        "source_options": ["manual", "existing_prompt"],
        "prompt_type": "t2v",
    },
    "prompt:first_frame_image": {
        "label": "First Frame Image Prompt",
        "type": "textarea",
        "source_options": ["manual", "existing_prompt"],
        "prompt_type": "first_frame_image",
    },
    "prompt:i2v": {
        "label": "I2V Prompt",
        "type": "textarea",
        "source_options": ["manual", "existing_prompt"],
        "prompt_type": "i2v",
    },
    "prompt:i2i": {
        "label": "I2I Prompt",
        "type": "textarea",
        "source_options": ["manual", "existing_prompt"],
        "prompt_type": "i2i",
    },
    "prompt:r2v_flash": {
        "label": "R2V Flash Prompt",
        "type": "textarea",
        "source_options": ["manual", "existing_prompt"],
        "prompt_type": "r2v_flash",
    },
    "artifact:first_frame_image": {
        "label": "First Frame Image",
        "type": "image",
        "source_options": ["upload", "existing_artifact"],
        "artifact_type": "first_frame_image",
    },
        "reference_images": {
            "label": "Reference Images",
            "type": "multi_image",
            "source_options": ["upload", "existing_artifact"],
            "artifact_type": "reference_image",
            "required": False,
        },
    "api_task:t2v": {
        "label": "T2V API Task",
        "type": "api_task",
        "source_options": [],
    },
    "api_task:first_frame_image": {
        "label": "First Frame Image API Task",
        "type": "api_task",
        "source_options": [],
    },
    "api_task:i2v": {
        "label": "I2V API Task",
        "type": "api_task",
        "source_options": [],
    },
    "i2i_test_batch": {
        "label": "I2I Test Batch",
        "type": "json",
        "source_options": [],
    },
    "artifact:i2i_test_first_frame_image": {
        "label": "I2I Test First Frame Image",
        "type": "image",
        "source_options": ["existing_artifact"],
        "artifact_type": "i2i_test_first_frame_image",
    },
    "api_task:i2i_test_image": {
        "label": "I2I Test Image API Task",
        "type": "api_task",
        "source_options": [],
    },
    "api_task:i2i_test_i2v": {
        "label": "I2I Test I2V API Task",
        "type": "api_task",
        "source_options": [],
    },
    "api_task:r2v_flash": {
        "label": "R2V Flash API Task",
        "type": "api_task",
        "source_options": [],
    },
}


class WorkflowValidator:
    NODE_DESCRIPTIONS = {
        "reverse_prompts": {
            "description_zh": "从源视频反推出基础文生视频提示词，是多数工作流的起点。输入为源视频，输出为可复用的 T2V Prompt。常用节点，属于核心路径。",
            "description_en": "Infers the base text-to-video prompt from the source video. Input is the source video; output is a reusable T2V prompt. Common node on the core path.",
        },
        "rewrite_prompts": {
            "description_zh": "将 T2V Prompt 改写为首帧图提示词和主路径 I2V Prompt。输入为 T2V Prompt，输出为 first_frame_image 与 i2v Prompt。常用节点，属于核心路径。",
            "description_en": "Rewrites the T2V prompt into first-frame image and main I2V prompts. Input is the T2V prompt; outputs are first_frame_image and i2v prompts. Common node on the core path.",
        },
        "reverse_prompts4r2v": {
            "description_zh": "将基础 T2V Prompt 改写为 R2V Flash 使用的参考图生视频提示词。输入为 T2V Prompt，输出为 r2v_flash Prompt。可选分支节点。",
            "description_en": "Rewrites the base T2V prompt into an R2V Flash prompt for reference-to-video generation. Input is the T2V prompt; output is the r2v_flash prompt. Optional branch node.",
        },
        "rewrite_t2i_to_i2i": {
            "description_zh": "将首帧图提示词改写为 I2I 测试提示词，用于验证图生图首帧效果。输入为 first_frame_image Prompt，输出为 i2i Prompt。I2I Test 分支常用节点。",
            "description_en": "Rewrites the first-frame image prompt into an I2I test prompt for validating generated first frames. Input is the first_frame_image prompt; output is the i2i prompt. Common on the I2I Test branch.",
        },
        "prepare_i2i_test_batch": {
            "description_zh": "根据 I2I Test 配置抽取测试素材并生成测试批次。输入为 i2i Prompt 与 mode/test_count/model 配置，输出为 i2i_test_batch 和测试源图产物。I2I Test 分支常用节点。",
            "description_en": "Builds the I2I test batch from mode, test count, model settings, and persona images. Inputs are the i2i prompt and test configuration; outputs are i2i_test_batch and source-image artifacts. Common on the I2I Test branch.",
        },
        "submit_i2i_test_image": {
            "description_zh": "使用 I2I Prompt 和测试源图提交首帧图生成任务。输入为 i2i Prompt 与 i2i_test_batch，输出为 I2I Test 图片 API Task。I2I Test 分支常用节点。",
            "description_en": "Submits image-generation tasks using the I2I prompt and test source images. Inputs are the i2i prompt and i2i_test_batch; output is I2I Test image API tasks. Common on the I2I Test branch.",
        },
        "poll_i2i_test_image": {
            "description_zh": "轮询 I2I Test 图片任务并下载生成的测试首帧图。输入为 I2I Test 图片 API Task，输出为 i2i_test_first_frame_image 产物。I2I Test 分支常用节点。",
            "description_en": "Polls I2I Test image tasks and downloads the generated test first frames. Input is I2I Test image API tasks; output is i2i_test_first_frame_image artifacts. Common on the I2I Test branch.",
        },
        "submit_i2i_test_i2v": {
            "description_zh": "使用 I2I 生成的测试首帧图和 I2V Prompt 提交测试视频任务。输入为 i2v Prompt、i2i_test_batch 与 i2i_test_first_frame_image，输出为 I2I Test I2V API Task。I2I Test 分支常用节点。",
            "description_en": "Submits test video tasks using generated I2I first frames and the I2V prompt. Inputs are the i2v prompt, i2i_test_batch, and i2i_test_first_frame_image; output is I2I Test I2V API tasks. Common on the I2I Test branch.",
        },
        "poll_i2i_test_i2v": {
            "description_zh": "轮询 I2I Test 视频任务并下载测试视频。输入为 I2I Test I2V API Task，输出为 i2i_test_video 产物。I2I Test 分支常用节点。",
            "description_en": "Polls I2I Test video tasks and downloads test videos. Input is I2I Test I2V API tasks; output is i2i_test_video artifacts. Common on the I2I Test branch.",
        },
        "submit_first_frame_image": {
            "description_zh": "根据首帧图提示词提交图片生成任务，生成后作为主路径 I2V 的输入。输入为 first_frame_image Prompt，输出为首帧图片 API Task。常用节点，属于主路径。",
            "description_en": "Submits image-generation using the first-frame prompt; the result becomes the main I2V input. Input is the first_frame_image prompt; output is a first-frame image API task. Common main-path node.",
        },
        "poll_first_frame_image": {
            "description_zh": "轮询首帧图任务并下载主路径首帧图。输入为首帧图片 API Task，输出为 first_frame_image 产物。常用节点，属于主路径。",
            "description_en": "Polls first-frame image tasks and downloads the main first-frame image. Input is a first-frame image API task; output is the first_frame_image artifact. Common main-path node.",
        },
        "submit_i2v": {
            "description_zh": "使用主路径首帧图和 I2V Prompt 提交图生视频任务。输入为 i2v Prompt 与 first_frame_image，输出为主路径 I2V API Task。常用节点，属于主路径。",
            "description_en": "Submits the main image-to-video task using the generated first frame and I2V prompt. Inputs are the i2v prompt and first_frame_image; output is the main I2V API task. Common main-path node.",
        },
        "poll_i2v": {
            "description_zh": "轮询主路径 I2V 任务并下载最终视频。输入为 I2V API Task，输出为 i2v_video 产物。常用节点，属于主路径。",
            "description_en": "Polls the main I2V task and downloads the final video. Input is an I2V API task; output is the i2v_video artifact. Common main-path node.",
        },
        "submit_t2v": {
            "description_zh": "使用 T2V Prompt 提交文生视频任务。输入为 t2v Prompt，输出为 T2V API Task。可选 T2V 分支节点。",
            "description_en": "Submits a text-to-video task using the T2V prompt. Input is the t2v prompt; output is a T2V API task. Optional T2V branch node.",
        },
        "poll_t2v": {
            "description_zh": "轮询 T2V 任务并下载文生视频结果。输入为 T2V API Task，输出为 t2v_video 产物。可选 T2V 分支节点，成功后会汇入 Manifest。",
            "description_en": "Polls T2V tasks and downloads text-to-video results. Input is a T2V API task; output is a t2v_video artifact. Optional branch node that feeds the manifest when enabled.",
        },
        "submit_r2v_flash": {
            "description_zh": "使用 R2V Prompt 和参考图提交参考图生视频任务。输入为 r2v_flash Prompt；reference_images 可由用户上传，未上传时从本地素材池随机抽取。输出为 R2V API Task。可选 R2V 分支节点。",
            "description_en": "Submits reference-to-video tasks using the R2V prompt. reference_images can be uploaded by the user; when omitted, local reference images are sampled automatically. Output is an R2V API task. Optional R2V branch node.",
        },
        "poll_r2v_flash": {
            "description_zh": "轮询 R2V 任务并下载参考图生视频结果。输入为 R2V API Task，输出为 r2v_flash_videos 产物。可选 R2V 分支节点，成功后会汇入 Manifest。",
            "description_en": "Polls R2V tasks and downloads reference-to-video results. Input is an R2V API task; output is r2v_flash_videos artifacts. Optional branch node that feeds the manifest when enabled.",
        },
        "export_manifest": {
            "description_zh": "导出 Job 汇总 Manifest，汇总提示词快照、API Task、产物、预算和错误。输入为已启用分支的成功节点结果，输出为 manifest artifact。常用收尾节点。",
            "description_en": "Exports the job manifest with prompt snapshots, API tasks, artifacts, budget, and errors. Inputs are successful results from enabled branches; output is the manifest artifact. Common final node.",
        },
        "failure_agent": {
            "description_zh": "用于失败诊断与错误摘要的可选 Agent 节点。输入为失败上下文，输出为错误分析事件或后续修复建议。可选诊断节点。",
            "description_en": "Optional agent node for failure diagnosis and error summaries. Input is failure context; output is diagnostic events or repair suggestions. Optional diagnostic node.",
        },
    }

    NODE_DEFINITIONS = {
        "reverse_prompts": {
            "order": 10,
            "can_start": True,
            "start_priority": 0,
            "required_inputs": ["source_video"],
            "produces": ["prompt:t2v"],
            "paired_with": [],
            "depends_on": [],
        },
        "rewrite_prompts": {
            "order": 40,
            "can_start": True,
            "start_priority": 1,
            "required_inputs": ["prompt:t2v"],
            "produces": ["prompt:first_frame_image", "prompt:i2v"],
            "paired_with": [],
            "depends_on": ["reverse_prompts"],
        },
        "reverse_prompts4r2v": {
            "order": 110,
            "can_start": True,
            "start_priority": 4,
            "required_inputs": ["prompt:t2v"],
            "produces": ["prompt:r2v_flash"],
            "paired_with": [],
            "depends_on": ["reverse_prompts"],
        },
        "rewrite_t2i_to_i2i": {
            "order": 65,
            "can_start": False,
            "start_priority": 99,
            "required_inputs": ["prompt:first_frame_image"],
            "produces": ["prompt:i2i"],
            "paired_with": [],
            "depends_on": ["rewrite_prompts"],
        },
        "prepare_i2i_test_batch": {
            "order": 66,
            "can_start": False,
            "start_priority": 99,
            "required_inputs": ["prompt:i2i"],
            "produces": ["i2i_test_batch"],
            "paired_with": [],
            "depends_on": ["rewrite_t2i_to_i2i"],
        },
        "submit_i2i_test_image": {
            "order": 67,
            "can_start": False,
            "start_priority": 99,
            "required_inputs": ["prompt:i2i", "i2i_test_batch"],
            "produces": ["api_task:i2i_test_image"],
            "paired_with": ["poll_i2i_test_image"],
            "depends_on": ["prepare_i2i_test_batch"],
        },
        "poll_i2i_test_image": {
            "order": 68,
            "can_start": False,
            "start_priority": 99,
            "required_inputs": ["api_task:i2i_test_image"],
            "produces": ["artifact:i2i_test_first_frame_image"],
            "paired_with": ["submit_i2i_test_image"],
            "depends_on": ["submit_i2i_test_image"],
        },
        "submit_i2i_test_i2v": {
            "order": 69,
            "can_start": False,
            "start_priority": 99,
            "required_inputs": ["prompt:i2v", "i2i_test_batch", "artifact:i2i_test_first_frame_image"],
            "produces": ["api_task:i2i_test_i2v"],
            "paired_with": ["poll_i2i_test_i2v"],
            "depends_on": ["poll_i2i_test_image"],
        },
        "poll_i2i_test_i2v": {
            "order": 70,
            "can_start": False,
            "start_priority": 99,
            "required_inputs": ["api_task:i2i_test_i2v"],
            "produces": ["artifact:i2i_test_video"],
            "paired_with": ["submit_i2i_test_i2v"],
            "depends_on": ["submit_i2i_test_i2v"],
        },
        "submit_first_frame_image": {
            "order": 50,
            "can_start": True,
            "start_priority": 2,
            "required_inputs": ["prompt:first_frame_image"],
            "produces": ["api_task:first_frame_image"],
            "paired_with": ["poll_first_frame_image"],
            "depends_on": ["rewrite_prompts"],
        },
        "poll_first_frame_image": {
            "order": 60,
            "can_start": False,
            "start_priority": 99,
            "required_inputs": ["api_task:first_frame_image"],
            "produces": ["artifact:first_frame_image"],
            "paired_with": ["submit_first_frame_image"],
            "depends_on": ["submit_first_frame_image"],
        },
        "submit_i2v": {
            "order": 80,
            "can_start": True,
            "start_priority": 3,
            "required_inputs": ["prompt:i2v", "artifact:first_frame_image"],
            "produces": ["api_task:i2v"],
            "paired_with": ["poll_i2v"],
            "depends_on": ["rewrite_prompts", "poll_first_frame_image"],
        },
        "poll_i2v": {
            "order": 90,
            "can_start": False,
            "start_priority": 99,
            "required_inputs": ["api_task:i2v"],
            "produces": ["artifact:i2v_video"],
            "paired_with": ["submit_i2v"],
            "depends_on": ["submit_i2v"],
        },
        "submit_t2v": {
            "order": 20,
            "can_start": True,
            "start_priority": 2,
            "required_inputs": ["prompt:t2v"],
            "produces": ["api_task:t2v"],
            "paired_with": ["poll_t2v"],
            "depends_on": ["reverse_prompts"],
        },
        "poll_t2v": {
            "order": 30,
            "can_start": False,
            "start_priority": 99,
            "required_inputs": ["api_task:t2v"],
            "produces": ["artifact:t2v_video"],
            "paired_with": ["submit_t2v"],
            "depends_on": ["submit_t2v"],
        },
        "submit_r2v_flash": {
            "order": 120,
            "can_start": True,
            "start_priority": 2,
            "required_inputs": ["prompt:r2v_flash"],
            "optional_inputs": ["reference_images"],
            "produces": ["api_task:r2v_flash"],
            "paired_with": ["poll_r2v_flash"],
            "depends_on": ["reverse_prompts4r2v"],
        },
        "poll_r2v_flash": {
            "order": 130,
            "can_start": False,
            "start_priority": 99,
            "required_inputs": ["api_task:r2v_flash"],
            "produces": ["artifact:r2v_flash_videos"],
            "paired_with": ["submit_r2v_flash"],
            "depends_on": ["submit_r2v_flash"],
        },
        "export_manifest": {
            "order": 990,
            "can_start": False,
            "start_priority": 99,
            "required_inputs": [],
            "produces": ["artifact:manifest"],
            "paired_with": [],
            "depends_on": ["poll_i2v", "poll_i2i_test_i2v", "poll_t2v", "poll_r2v_flash"],
        },
        "failure_agent": {
            "order": 980,
            "can_start": False,
            "start_priority": 99,
            "required_inputs": [],
            "produces": [],
            "paired_with": [],
            "depends_on": [],
        },
    }

    @classmethod
    def validate(
        cls,
        enabled_nodes: list[str],
        disabled_nodes: list[str],
        initial_prompts: dict,
        initial_artifacts: dict,
    ) -> dict:
        defs = cls.NODE_DEFINITIONS
        errors = []
        warnings = []
        enabled_set = {node for node in enabled_nodes if node in defs}
        available_resources = cls._available_resources(initial_prompts, initial_artifacts)

        for submit_key, poll_key in cls._submit_poll_pairs():
            if poll_key in enabled_set and submit_key not in enabled_set:
                errors.append({
                    "code": "DEPENDENCY_MISSING",
                    "message": f"{poll_key} requires {submit_key}.",
                    "nodes": [poll_key, submit_key],
                })
            if submit_key in enabled_set and poll_key not in enabled_set:
                warnings.append({
                    "code": "PAIR_INCOMPLETE",
                    "message": f"{submit_key} is enabled without {poll_key}.",
                    "nodes": [submit_key, poll_key],
                })

        cls._append_semantic_dependency_errors(enabled_set, available_resources, errors)
        sorted_nodes = sorted(enabled_set, key=lambda key: defs[key].get("order", 99))

        selected_generated_outputs = cls._selected_generated_outputs(enabled_set)
        manual_input_keys = cls._manual_input_keys(
            enabled_set=enabled_set,
            available_resources=available_resources,
            selected_generated_outputs=selected_generated_outputs,
        )
        required_inputs_by_key = {
            key: cls._input_descriptor(key)
            for key in sorted(manual_input_keys, key=cls._input_sort_key)
        }
        optional_input_keys = cls._optional_input_keys(
            enabled_set=enabled_set,
            available_resources=available_resources,
            selected_generated_outputs=selected_generated_outputs,
            required_input_keys=set(required_inputs_by_key),
        )
        optional_inputs_by_key = {
            key: cls._input_descriptor(key, required=False)
            for key in sorted(optional_input_keys, key=cls._input_sort_key)
        }

        inferred_available = set(available_resources) | selected_generated_outputs | set(manual_input_keys)
        node_satisfied = {}
        for node_key in sorted_nodes:
            meta = defs[node_key]
            node_satisfied[node_key] = all(
                req in inferred_available
                for req in meta.get("required_inputs", [])
            )

        start_nodes = cls._start_nodes(sorted_nodes, enabled_set)
        required_inputs = list(required_inputs_by_key.values())
        optional_inputs = list(optional_inputs_by_key.values())
        return {
            "valid": len(errors) == 0,
            "start_nodes": start_nodes,
            "required_inputs": required_inputs,
            "optional_inputs": optional_inputs,
            "warnings": warnings,
            "errors": errors,
            "node_satisfied": node_satisfied,
        }

    @staticmethod
    def _submit_poll_pairs() -> list[tuple[str, str]]:
        return [
            ("submit_t2v", "poll_t2v"),
            ("submit_first_frame_image", "poll_first_frame_image"),
            ("submit_i2v", "poll_i2v"),
            ("submit_i2i_test_image", "poll_i2i_test_image"),
            ("submit_i2i_test_i2v", "poll_i2i_test_i2v"),
            ("submit_r2v_flash", "poll_r2v_flash"),
        ]

    @staticmethod
    def _append_semantic_dependency_errors(
        enabled_set: set[str],
        available_resources: set[str],
        errors: list[dict],
    ) -> None:
        return None

    @classmethod
    def _selected_generated_outputs(cls, enabled_set: set[str]) -> set[str]:
        outputs = set()
        for node_key in enabled_set:
            outputs.update(cls.NODE_DEFINITIONS.get(node_key, {}).get("produces", []))
        return outputs

    @classmethod
    def _manual_input_keys(
        cls,
        enabled_set: set[str],
        available_resources: set[str],
        selected_generated_outputs: set[str],
    ) -> set[str]:
        required = set()
        for node_key in enabled_set:
            required.update(cls.NODE_DEFINITIONS.get(node_key, {}).get("required_inputs", []))
        return required - selected_generated_outputs - available_resources

    @classmethod
    def _optional_input_keys(
        cls,
        enabled_set: set[str],
        available_resources: set[str],
        selected_generated_outputs: set[str],
        required_input_keys: set[str],
    ) -> set[str]:
        optional = set()
        for node_key in enabled_set:
            optional.update(cls.NODE_DEFINITIONS.get(node_key, {}).get("optional_inputs", []))
        return optional - selected_generated_outputs - available_resources - required_input_keys

    @staticmethod
    def _input_sort_key(key: str) -> tuple[int, str]:
        order = {
            "source_video": 0,
            "prompt:t2v": 10,
            "prompt:first_frame_image": 20,
            "prompt:i2v": 30,
            "prompt:i2i": 40,
            "prompt:r2v_flash": 50,
            "artifact:first_frame_image": 60,
            "artifact:i2i_test_first_frame_image": 65,
            "reference_images": 70,
            "i2i_test_batch": 80,
        }
        if key.startswith("api_task:"):
            return (900, key)
        return (order.get(key, 500), key)

    @staticmethod
    def _available_resources(initial_prompts: dict, initial_artifacts: dict) -> set[str]:
        resources = set()
        for prompt_type, value in (initial_prompts or {}).items():
            if WorkflowValidator._has_prompt_value(value):
                resources.add(f"prompt:{prompt_type}")
        for artifact_key, value in (initial_artifacts or {}).items():
            if not WorkflowValidator._has_artifact_value(value):
                continue
            if artifact_key in {"source_video", "reference_images", "i2i_test_batch"}:
                resources.add(artifact_key)
            else:
                resources.add(f"artifact:{artifact_key}")
        return resources

    @classmethod
    def _start_nodes(cls, sorted_nodes: list[str], enabled_set: set[str]) -> list[str]:
        candidates = [
            key for key in sorted_nodes
            if cls.NODE_DEFINITIONS[key].get("can_start", False)
            and not any(dep in enabled_set for dep in cls.NODE_DEFINITIONS[key].get("depends_on", []))
        ]
        if not candidates:
            return []
        return candidates

    @staticmethod
    def _input_descriptor(key: str, required: bool | None = None) -> dict:
        definition = INPUT_DEFINITIONS.get(key, {})
        return {
            "key": key,
            "label": definition.get("label", key),
            "type": definition.get("type", "text"),
            "required": definition.get("required", True) if required is None else required,
            "source_options": definition.get("source_options", []),
            **({"prompt_type": definition["prompt_type"]} if definition.get("prompt_type") else {}),
            **({"artifact_type": definition["artifact_type"]} if definition.get("artifact_type") else {}),
        }

    @staticmethod
    def _has_prompt_value(value) -> bool:
        if isinstance(value, dict):
            return bool(
                str(value.get("content") or "").strip()
                or value.get("prompt_id")
                or value.get("prompt_version_id")
                or value.get("version")
            )
        if isinstance(value, str):
            return bool(value.strip())
        return bool(value)

    @staticmethod
    def _has_artifact_value(value) -> bool:
        if isinstance(value, dict):
            return bool(
                value.get("artifact_id")
                or value.get("artifact_ids")
                or value.get("file_path")
                or value.get("uploaded")
            )
        if isinstance(value, list):
            return any(WorkflowValidator._has_artifact_value(item) for item in value)
        if isinstance(value, str):
            return bool(value.strip())
        return bool(value)
