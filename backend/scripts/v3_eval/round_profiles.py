"""Fixed evaluation profiles; historical thresholds are never upgraded in place."""
from copy import deepcopy

_PROFILES = {
    "V12": {"round": "V12-Gate5b", "prefix": "cinecrew-v12-", "marker_file": "v12-round.json",
        "marker": {"round": "V12-Gate5b", "call_limit": 150, "real_image_limit": 0,
                   "real_video_limit": 0, "media_mode": "mock"},
        "input_token_limit": 60000, "expected": {"c7_complete_story": 1, "c3_story": 2, "c1_portrait": 1},
        "require_review_b": True},
    "V13": {"round": "V13-Gate6", "prefix": "cinecrew-v13-", "marker_file": "v13-round.json",
        "marker": {"round": "V13-Gate6", "call_limit": 120, "real_image_limit": 6,
                   "real_video_limit": 0, "media_mode": "identity_sample"},
        "input_token_limit": 80000, "expected": {"c7_complete_story": 1, "c3_story": 2},
        "require_review_b": False,
        "planning_labels": {"01-c3-1": "c3_story", "02-c3-2": "c3_story", "03-c7": "c7_complete_story"}},
}


def round_profile(name):
    if not isinstance(name, str) or name not in _PROFILES:
        raise ValueError("An explicit V12 or V13 evaluation profile is required")
    return {"name": name, **deepcopy(_PROFILES[name])}
