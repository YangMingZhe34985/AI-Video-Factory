"""Model preferences written as sentences still select the named models (real-provider E2E F3/F4)."""

import pytest

from app.agent.model_selection import candidates_for_request, constraints_for_mode


def spec(preferences=(), exclusions=(), deliverable="video"):
    return {"deliverable": deliverable, "recipe_hint": "single_clip" if deliverable == "video" else "image_create",
            "summary": "测试", "attachments": [], "confidence": 0.9,
            "constraints": {"model_preferences": list(preferences), "model_exclusions": list(exclusions)}}


def ids(value, mode):
    return [item.model_id for item in candidates_for_request(value, mode)]


@pytest.mark.parametrize("sentence", ["图片使用wan2.7-image模型", "图片用 Wan2.7-Image", "wan2.7-image"])
def test_image_model_named_in_a_sentence_constrains_images_only(app_ctx, sentence):
    value = spec([sentence])
    assert ids(value, "t2i") == ["wan2.7-image"]
    assert constraints_for_mode(value, "i2v") == ([], [])
    assert ids(value, "i2v") == ["wan2.7-i2v"]  # unconstrained video keeps the server default


@pytest.mark.parametrize("sentence", ["视频使用wan2.7-i2v模型", "wan2.7-i2v"])
def test_video_model_named_in_a_sentence_constrains_video_only(app_ctx, sentence):
    value = spec([sentence])
    assert ids(value, "i2v") == ["wan2.7-i2v"]
    assert constraints_for_mode(value, "t2i") == ([], [])


@pytest.mark.parametrize("sentence", ["全部使用wan2.7系列模型", "wan2.7系列", "尽量选用wan2.7模型"])
def test_family_preference_covers_both_images_and_videos(app_ctx, sentence):
    value = spec([sentence])
    assert set(ids(value, "t2i")) <= {"wan2.7-image", "wan2.7-image-pro"} and ids(value, "t2i")
    assert ids(value, "i2v") == ["wan2.7-i2v"]
    assert ids(value, "t2v") == ["wan2.7-t2v"]
    # The brief text is returned unchanged for callers that edit preferences.
    assert constraints_for_mode(value, "i2v")[0] == [sentence]


def test_two_models_in_one_sentence_each_apply_to_their_own_type(app_ctx):
    value = spec(["图片用wan2.7-image，视频用wan2.7-i2v"])
    assert ids(value, "t2i") == ["wan2.7-image"]
    assert ids(value, "i2v") == ["wan2.7-i2v"]


def test_longest_name_wins_and_versions_do_not_bleed(app_ctx):
    assert ids(spec(["请用wan2.70系列"]), "i2v") == []  # unknown version must not become wan2.7
    assert ids(spec(["使用完全不存在的foo模型"]), "i2v") == []  # unknown names still fail visibly


def test_exclusion_sentence_removes_the_named_family(app_ctx):
    value = spec(["wan2.7系列"], ["不要用happy-horse"])
    assert ids(value, "i2v") == ["wan2.7-i2v"]


@pytest.mark.parametrize("sentence", ["只用wan2.7系列视频模型", "wan2.7 video models", "图生视频用wan2.7系列"])
def test_video_scope_word_keeps_a_family_off_images(app_ctx, sentence):
    value = spec([sentence])
    assert ids(value, "i2v") == ["wan2.7-i2v"]
    assert constraints_for_mode(value, "t2i") == ([], [])


def test_image_scope_word_keeps_a_family_off_video(app_ctx):
    value = spec(["图片也用wan2.7系列"])
    assert set(ids(value, "t2i")) <= {"wan2.7-image", "wan2.7-image-pro"}
    assert constraints_for_mode(value, "i2v") == ([], [])
