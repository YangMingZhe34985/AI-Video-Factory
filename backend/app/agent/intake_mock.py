"""Deterministic offline examples, not a substitute for LLM understanding."""

import re

from app.agent.clarify import answer_for


def _duration(text):
    match = re.search(r"(\d+|[一二两三四五六七八九十]+)\s*(分钟|分(?!镜)|秒|minutes?|seconds?|min|sec|s\b)", text, re.I)
    if not match:
        return None
    value, unit = match.groups()
    digits = dict(zip("一二两三四五六七八九", [1, 2, 2, 3, 4, 5, 6, 7, 8, 9]))
    if value.isdigit():
        count = int(value)
    elif "十" in value:
        left, right = value.split("十", 1)
        count = digits.get(left, 1) * 10 + digits.get(right, 0)
    else:
        count = digits.get(value)
    return count * (60 if unit.lower().startswith(("分", "min")) else 1) if count else None


def _model_mentions(text):
    preferences, exclusions = [], []
    pattern = r"(不要使用|不使用|不要调用|不要用|禁止使用|禁止调用|禁止|排除|不用|使用|采用|指定|选择|用)\s*([A-Za-z][\w.\-]*(?:系列)?)"
    for match in re.finditer(pattern, text):
        verb, label = match.groups()
        target = exclusions if verb.startswith(("不", "禁止", "排除")) else preferences
        target.append(label)
    return preferences, exclusions


def _answer(data, question_id):
    answer = answer_for({"clarifications": data.clarifications}, question_id, asked_by="intake")
    return (answer.get("option_id") or answer.get("text")) if answer else None


def mock_request_spec(data):
    text = data.text
    duration = _duration(text)
    videos = [item for item in data.attachments if item.kind == "video"]
    images = [item for item in data.attachments if item.kind == "image"]
    motion = any(word in text for word in ("视频", "短片", "影片", "故事片", "动起来", "拍片", "一部片", "动画"))
    editing = bool(videos) and any(word in text for word in ("替换", "保留", "删掉", "剪掉", "修改", "改造", "剪辑", "改成"))
    style_only = any(word in text for word in ("风格", "画风")) and any(word in text for word in ("参考", "按照", "按这", "模仿"))
    if editing:
        recipe = "remix"
    elif motion or duration:
        recipe = "story_video" if (duration and duration > 30) or any(word in text for word in ("故事", "剧情", "多镜头")) else "single_clip"
    else:
        recipe = "image_edit" if images and not style_only else "image_create"
    uses = []
    identity = any(word in text for word in ("我", "人像", "西装", "证件照", "头像", "脸", "人物"))
    attachment_choice = _answer(data, "attachment_use")
    for item in data.attachments:
        if item.kind == "video" and recipe == "remix" and item == videos[0]:
            role = "remix_source"
        elif style_only or attachment_choice == "style" or "风格" in (attachment_choice or ""):
            role = "style_ref"
        elif item.kind == "image" and recipe == "image_edit":
            role = "identity_ref" if identity else "content_ref"
        elif item.kind == "image" and recipe == "single_clip" and item == images[0]:
            role = "first_frame"
        else:
            role = "content_ref"
        uses.append({"attachment_id": item.attachment_id, "kind": item.kind, "role": role,
                     "description": item.description, "reason": "Mock：根据需求和附件类型提出用途，供后续确认。"})
    questions = []
    explicit_use = any(word in text for word in ("参考", "风格", "保留", "修改", "改成", "动起来", "照片", "首帧"))
    if data.attachments and motion and not explicit_use and not attachment_choice:
        questions.append({
            "question_id": "attachment_use", "text": "附件主要用来保留内容，还是参考风格？",
            "why": "附件用途会影响人物一致性和后续制作方案。",
            "options": [{"option_id": "content", "label": "保留主体与内容"},
                        {"option_id": "style", "label": "仅参考风格"}],
            "recommended_option_id": "content", "default_option_id": "content",
            "allow_free_text": True, "blocking": True,
        })
    count_match = re.search(r"(\d+|[一二两三四])\s*张", text)
    count_text = count_match.group(1) if count_match else "1"
    count = int(count_text) if count_text.isdigit() else {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4}[count_text]
    preferences, exclusions = _model_mentions(text)
    research = [{"query": text[:200], "reason": "需要查证用户提到的最新概念或拟人形象。"}] if any(
        word in text for word in ("拟人", "漫化", "二次元娘", "最新", "流行", "热门")
    ) else []
    aspect = next((value for value in ("16:9", "9:16", "1:1", "4:3", "3:4") if value in text), None)
    compress = bool(re.search(r"(?:需要|请|要求|进行|输出时)压缩", text)) and not re.search(r"(?:不|无需|禁止)[^，。！？]{0,8}压缩", text)
    return {
        "deliverable": "image" if recipe.startswith("image_") else "video", "recipe_hint": recipe,
        "summary": text[:500], "output_count": count if recipe.startswith("image_") else 1, "target_duration_sec": None if recipe.startswith("image_") else duration,
        "aspect_ratio": aspect, "subjects": [{"name": "主要主体", "description": text[:1000],
                                              "source": "user_text", "attachment_ids": []}],
        "attachments": uses,
        "constraints": {"model_preferences": preferences, "model_exclusions": exclusions,
                        "compress_output": bool(compress)},
        "research_needs": research, "open_questions": questions, "confidence": 0.7 if questions else 0.9,
    }
