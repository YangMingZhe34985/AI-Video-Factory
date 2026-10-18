from app.tools.specs import (
    analyze_image,
    analyze_video,
    compose_video,
    probe_media,
    qc_video,
    package_story,
    animate_shot,
    download_reference,
    extract_frame,
    fetch_page,
    web_search,
    generate_image,
    generate_video,
    transform_video,
    capture_reference_page,
    get_task_status,
    image_search,
    package_project,
    produce_shot,
    remix_shot,
    rerun_node,
    rewrite_prompt,
)

# V3 metadata is additive; legacy API descriptions and handlers stay unchanged.
from dataclasses import replace

_AGENT_VISIBLE = {"analyze_video", "web_search", "image_search", "fetch_page",
                  "download_reference", "capture_reference_page", "get_task_status"}
_PLAN_IO = {
    "generate_image": {"inputs": {"prompt": "text", "reference_artifact_ids": "image[]"},
                       "outputs": {"image": "image", "images": "image[]"}},
    "animate_shot": {"inputs": {"prompt": "text", "first_frame_artifact_id": "image", "last_frame_artifact_id": "image"},
                     "outputs": {"video": "video"}},
    "generate_video": {"inputs": {"prompt": "text", "first_frame_artifact_id": "image", "reference_artifact_ids": "image[]"},
                       "outputs": {"video": "video"}},
    "transform_video": {"inputs": {"plan_hash": "text"}, "outputs": {"video": "video"}},
    "extract_frame": {"inputs": {"video_artifact_id": "video"}, "outputs": {"artifact_id": "image"}},
    "compose_video": {"inputs": {"video_artifact_ids": "video[]"},
                      "outputs": {"artifact_id": "video", "compressed_artifact_id": "video"}},
    "probe_media": {"inputs": {"artifact_id": "video"}, "outputs": {"media": "json"}},
    "qc_video": {"inputs": {"artifact_id": "video", "video_artifact_ids": "video[]"},
                 "outputs": {"passed": "json", "checks": "json", "warnings": "json"}},
    "package_story": {"inputs": {"artifact_id": "video", "compressed_artifact_id": "video"},
                      "outputs": {"artifact_id": "package"}},
}
for _name in _AGENT_VISIBLE | _PLAN_IO.keys():
    _module = globals()[_name]
    _module.SPEC = replace(_module.SPEC, agent_visible=_name in _AGENT_VISIBLE,
                          plan_executable=_name in _PLAN_IO, io_types=_PLAN_IO.get(_name, {}))

ALL_SPECS = [
    web_search.SPEC,
    fetch_page.SPEC,
    analyze_image.SPEC,
    analyze_video.SPEC,
    compose_video.SPEC,
    probe_media.SPEC,
    qc_video.SPEC,
    package_story.SPEC,
    animate_shot.SPEC,
    download_reference.SPEC,
    extract_frame.SPEC,
    image_search.SPEC,
    rewrite_prompt.SPEC,
    generate_image.SPEC,
    generate_video.SPEC,
    transform_video.SPEC,
    capture_reference_page.SPEC,
    get_task_status.SPEC,
    rerun_node.SPEC,
    package_project.SPEC,
    produce_shot.SPEC,
    remix_shot.SPEC,
]
