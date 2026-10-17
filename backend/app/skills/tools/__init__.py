from app.skills.tools import (
    analyze_image,
    analyze_video,
    animate_shot,
    generate_image,
    generate_video,
    get_task_status,
    package_project,
    produce_shot,
    remix_shot,
    rerun_node,
    rewrite_prompt,
)

ALL_SPECS = [
    analyze_image.SPEC,
    analyze_video.SPEC,
    animate_shot.SPEC,
    rewrite_prompt.SPEC,
    generate_image.SPEC,
    generate_video.SPEC,
    get_task_status.SPEC,
    rerun_node.SPEC,
    package_project.SPEC,
    produce_shot.SPEC,
    remix_shot.SPEC,
]
