"""Authoring guidance keeps user duration, event completion and review provenance."""
from pathlib import Path
import re

import pytest

from app.agents.schemas import RequirementBrief

BACKEND = Path(__file__).resolve().parents[1]


def read(relative):
    return (BACKEND / relative).read_text(encoding='utf-8')


@pytest.mark.parametrize('relative', ['app/agents/prompts/director.md', 'skills/plan-review/SKILL.md'])
def test_v12_review_marker_is_updated_without_claiming_v13_approval(relative):
    text = read(relative)
    assert 'V12f 最终候选审阅规则（已由 Claude 审定 · V-Gate5b）' in text
    assert '待 Claude V-Gate5b 审阅' not in text
    assert 'V13a · 待 Claude V-Gate6 审阅' in text


@pytest.mark.parametrize('relative', ['app/agents/prompts/director.md', 'skills/long-form-video/SKILL.md'])
def test_fixed_event_guidance_requires_completion_in_actual_shot_prompts(relative):
    text = read(relative)
    section = text.split('## 固定事件完成（V13d · 待 Claude V-Gate6 审阅）', 1)[1].split('\n## ', 1)[0]
    assert all(word in section for word in ['实际视频提示词', '完成状态', '准备', 'Producer'])
    assert '不是生成成功证据' in section


@pytest.mark.parametrize('target', [2, 12, 40, 96, 300])
def test_documented_approx_formula_matches_schema_without_sample_specific_tuning(target):
    text = read('skills/long-form-video/SKILL.md')
    match = re.search(r'approx 容差为 max\((\d+)秒,目标([\d.]+)%\)', text)
    assert match
    floor, percent = map(float, match.groups())
    brief = RequirementBrief(deliverable='video', summary='explicit duration', confidence=1,
                              target_duration_sec=target, duration_mode='approx')
    assert brief.duration_tolerance_sec == max(floor, target * percent / 100)
    assert 'exact/at_most 容差为0' in text


def test_no_story_or_model_derived_user_target_and_no_obsolete_fixed_tolerance():
    long_text = read('skills/long-form-video/SKILL.md')
    assert '没有明确时长则不填写用户目标' in long_text
    assert '不能根据故事长度、镜头数或模型时长反推' in long_text
    assert '用户明确' in long_text and 'duration_source_text' in long_text
    for relative in ['skills/long-form-video/SKILL.md', 'skills/plan-review/SKILL.md',
                     'skills/intent-analysis/SKILL.md', 'app/agents/prompts/director.md']:
        assert not re.search(r'通常\s*±\s*10\s*秒', read(relative))
    assert int(re.search(r'^version: (\d+)$', long_text, re.M).group(1)) >= 4
    assert int(re.search(r'^version: (\d+)$', read('skills/plan-review/SKILL.md'), re.M).group(1)) >= 10
