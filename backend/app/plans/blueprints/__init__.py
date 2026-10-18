"""Repository-owned deterministic builders. They never execute generated plans."""
from app.plans.blueprints import image_create, image_edit, single_clip, story_video, video_remix, video_transform
from app.plans.blueprints.common import VERSION

BUILDERS = {
    "image-create": (image_create.Params, image_create.build),
    "image-edit": (image_edit.Params, image_edit.build),
    "single-clip": (single_clip.Params, single_clip.build),
    "story-video": (story_video.Params, story_video.build),
    "video-remix": (video_remix.Params, video_remix.build),
    "video-transform": (video_transform.Params, video_transform.build),
}
