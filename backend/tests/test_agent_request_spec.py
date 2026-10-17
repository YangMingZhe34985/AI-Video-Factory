"""Contract-level Intake examples and semantic validation, without model calls."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.agent.clarify import Question
from app.agent.intake import IntakeInput
from app.agent.intake_mock import mock_request_spec
from app.agent.request_spec import RequestSpec, validate_request_spec


EXAMPLES = [
    (("生成我的一张西装照", "请把这张人像换成西装照"), "image", "image_edit", "identity_ref", None),
    (("把杯子改成红色", "请将图片里的杯子换成红色"), "image", "image_edit", "content_ref", None),
    (("生成一张橘猫插画", "画一张可爱的橘猫插画"), None, "image_create", None, None),
    (("按这张图的水彩风格画海边", "参考上传图片的画风，画海边"), "image", "image_create", "style_ref", None),
    (("生成 5 秒猫跳舞视频", "请做猫跳舞的视频，时长五秒"), None, "single_clip", None, 5),
    (("让照片里的猫动起来", "把图中的猫做成视频，让它动起来"), "image", "single_clip", "first_frame", None),
    (("做一个两分钟的最新 AI 拟人故事视频", "最新 AI 拟人的剧情短片，大概 2 分钟"), None, "story_video", None, 120),
    (("保留原视频前半段，把后半段改成森林", "修改这个视频，保留开头，替换后半段"), "video", "remix", "remix_source", None),
    (("参考视频风格制作两分钟故事片", "做 120 秒剧情视频，模仿附件画风"), "video", "story_video", "style_ref", 120),
    (("用这些素材做一部片", "请用附件做一个视频"), "image", "single_clip", "first_frame", None),
]


@pytest.mark.parametrize("variants,kind,recipe,role,duration", EXAMPLES)
def test_mock_examples_and_wording_variants(variants, kind, recipe, role, duration):
    for text in variants:
        attachments = [{"attachment_id": "art_ref", "kind": kind, "description": "图片或视频的分析内容"}] if kind else []
        data = IntakeInput(text=text, attachments=attachments)
        spec = validate_request_spec(mock_request_spec(data), attachments)
        assert spec.recipe_hint == recipe
        assert spec.deliverable == ("image" if recipe.startswith("image_") else "video")
        assert spec.target_duration_sec == duration
        assert spec.constraints.compress_output is False
        assert [item.role for item in spec.attachments] == ([role] if kind else [])
        assert spec.attachments == [] or spec.attachments[0].description == attachments[0]["description"]
        if "拟人" in text:
            assert spec.research_needs
        if "素材" in text or "附件做" in text:
            assert len(spec.open_questions) == 1
            assert isinstance(spec.open_questions[0], Question)


def base_spec():
    return {"deliverable": "image", "recipe_hint": "image_create", "summary": "画猫", "confidence": 0.9}


@pytest.mark.parametrize("update", [
    {"target_duration_sec": 5}, {"target_duration_sec": True}, {"confidence": float("nan")},
    {"recipe_hint": "single_clip"}, {"recipe_hint": "image_edit"}, {"extra": "not allowed"},
    {"subjects": [{"name": "猫", "description": "猫", "source": "attachment", "attachment_ids": ["missing"]}]},
])
def test_rejects_invalid_request_semantics(update):
    with pytest.raises(ValidationError):
        RequestSpec.model_validate({**base_spec(), **update})


def test_attachment_coverage_kinds_and_reference_rules():
    image = {"attachment_id": "art_1", "kind": "image", "role": "content_ref", "description": "杯子", "reason": "改色"}
    valid = {**base_spec(), "recipe_hint": "image_edit", "attachments": [image]}
    assert validate_request_spec(valid, [{"attachment_id": "art_1", "kind": "image"}])
    for expected in ([], [{"attachment_id": "other", "kind": "image"}], [{"attachment_id": "art_1", "kind": "video"}]):
        with pytest.raises(ValueError):
            validate_request_spec(valid, expected)
    for uses in ([image, image], [{**image, "role": "remix_source"}]):
        with pytest.raises(ValidationError):
            RequestSpec.model_validate({**valid, "attachments": uses})
    with pytest.raises(ValidationError):
        RequestSpec.model_validate({**base_spec(), "attachments": [{**image, "kind": "video", "role": "first_frame"}]})


def test_video_count_and_remix_source_cardinality():
    video = {"deliverable": "video", "recipe_hint": "remix", "summary": "修改片段", "confidence": 0.8}
    source = {"attachment_id": "art_1", "kind": "video", "role": "remix_source", "description": "原视频", "reason": "保留"}
    assert RequestSpec.model_validate({**video, "attachments": [source]})
    for uses in ([], [source, {**source, "attachment_id": "art_2"}]):
        with pytest.raises(ValidationError):
            RequestSpec.model_validate({**video, "attachments": uses})
    with pytest.raises(ValidationError):
        RequestSpec.model_validate({**video, "attachments": [source], "output_count": 2})


@pytest.mark.parametrize("recipe", ["single_clip", "story_video"])
def test_video_can_be_an_identity_reference_without_becoming_remix(recipe):
    raw = {"deliverable": "video", "recipe_hint": recipe, "summary": "参考视频中的人物创作新故事", "confidence": 0.8,
           "attachments": [{"attachment_id": "art_1", "kind": "video", "role": "identity_ref",
                            "description": "用户上传的人物视频", "reason": "保持主角身份，内容重新创作"}]}
    spec = validate_request_spec(raw, [{"attachment_id": "art_1", "kind": "video"}])
    assert spec.recipe_hint == recipe
    assert spec.attachments[0].role == "identity_ref"


def test_preserves_model_spelling_and_explicit_compression():
    spec = RequestSpec.model_validate(mock_request_spec(IntakeInput(
        text="生成视频，使用 WAN2.7系列，禁止 HappyHorse，请压缩输出，9:16"
    )))
    assert spec.constraints.model_preferences == ["WAN2.7系列"]
    assert spec.constraints.model_exclusions == ["HappyHorse"]
    assert spec.constraints.compress_output is True
    assert spec.aspect_ratio == "9:16"


def test_clarification_answers_change_use_without_repeating_question():
    data = IntakeInput(text="用这些素材做一部片", attachments=[
        {"attachment_id": "art_1", "kind": "image", "description": "原图"}
    ])
    initial = RequestSpec.model_validate(mock_request_spec(data))
    assert initial.open_questions
    answered = deepcopy(data)
    answered.clarifications = [{"card": {"asked_by": "intake"}, "answers": {"attachment_use": {"option_id": "style"}}}]
    revised = RequestSpec.model_validate(mock_request_spec(answered))
    assert revised.open_questions == []
    assert revised.attachments[0].role == "style_ref"
    answered.clarifications = [{"card": {"asked_by": "intake"}, "answers": {"attachment_use": {"text": "只参考风格"}}}]
    revised = RequestSpec.model_validate(mock_request_spec(answered))
    assert revised.open_questions == []
    assert revised.attachments[0].role == "style_ref"


def test_model_constraints_cannot_be_invented_or_resolved_early():
    raw = {**base_spec(), "constraints": {"model_preferences": ["wan2.7-i2v"]}}
    with pytest.raises(ValueError, match="original wording"):
        validate_request_spec(raw, [], source_text="使用 wan2.7 系列制作")
    raw["constraints"]["model_preferences"] = ["wan2.7"]
    assert validate_request_spec(raw, [], source_text="使用 wan2.7 系列制作")


@pytest.mark.parametrize("text", ["生成视频，不需要压缩", "生成视频，请不要进行压缩"])
def test_mock_compression_requires_positive_request(text):
    spec = RequestSpec.model_validate(mock_request_spec(IntakeInput(text=text)))
    assert spec.constraints.compress_output is False
