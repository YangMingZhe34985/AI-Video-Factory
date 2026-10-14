from app.skills.tools import (
    analyze_video,
    generate_image,
    generate_video,
    get_task_status,
    package_project,
    produce_shot,
    rerun_node,
    rewrite_prompt,
)

ALL_SPECS = [
    analyze_video.SPEC,
    rewrite_prompt.SPEC,
    generate_image.SPEC,
    generate_video.SPEC,
    get_task_status.SPEC,
    rerun_node.SPEC,
    package_project.SPEC,
    produce_shot.SPEC,
]
