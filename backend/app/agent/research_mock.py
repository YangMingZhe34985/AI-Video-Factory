"""Deterministic offline research fixtures, never claims about real popularity."""

from app.agent.research_spec import analysis_traits


def plan(data):
    spec = data.request_spec
    text = spec.summary.lower()
    names = [item.name for item in spec.subjects if item.source == "needs_research"]
    if any(word in text for word in ("拟人", "漫化", "二次元娘")):
        names = [name for name in ("DeepSeek", "ChatGPT") if name.lower() in text or "ai" in text]
    names = list(dict.fromkeys(names))[:4]
    queries = list(dict.fromkeys(item.query for item in spec.research_needs))[:4]
    maximum = data.limits["queries"]
    images = [{"entity": name, "query": f"{name} 形象参考"} for name in names[:maximum]]
    queries = queries[:max(0, maximum - len(images))]
    return {"web_queries": queries, "image_queries": images}


def select(data):
    hits = data.untrusted_content["hits"]
    entities = list(dict.fromkeys(hit["entity"] for hit in hits if hit["kind"] == "image"))
    remaining = data.limits["downloads"]
    groups = []
    for name in entities:
        ids = [hit["result_id"] for hit in hits if hit["kind"] == "image" and hit["entity"] == name][:min(3, remaining)]
        if ids:
            groups.append({"entity": name, "result_ids": ids})
            remaining -= len(ids)
    return {"page_ids": [hit["result_id"] for hit in hits if hit["kind"] == "web"][:data.limits["pages"]],
            "images": groups}


def synthesize(data):
    content = data.untrusted_content
    sources = content["sources"][:40]
    ids = {source["source_id"] for source in sources}
    web = [source for source in sources if source["kind"] == "web"]
    topics = [{"topic_id": "topic_demo", "query": data.request_spec.summary[:200],
               "summary": "Mock 离线演示资料，用于验证检索、来源与确认流程，不代表真实潮流或主流形象。",
               "key_facts": [{"fact": "演示候选存在多种外观，需要按用户偏好确认。", "source_ids": [web[0]["source_id"]]}],
               "confidence": 0.5}] if web else []
    names = list(dict.fromkeys(item["entity"] for item in content["images"]))
    entities = []
    for index, name in enumerate(names):
        images = [item for item in content["images"] if item["entity"] == name
                  and item["reference_id"] in content["analyses"] and item["source_id"] in ids]
        candidates = [{"candidate_id": f"e{index + 1}_c{number + 1}", "reference_id": item["reference_id"],
                       "source_id": item["source_id"], "traits": analysis_traits(content["analyses"][item["reference_id"]]),
                       "popularity_hint": "high" if name == "DeepSeek" and number == 0 else "medium",
                       "why": "离线虚构候选，仅验证功能。"} for number, item in enumerate(images[:4])]
        entities.append({"entity_id": f"e{index + 1}", "name": name, "description": "Mock 参考形象，非真实角色设定。",
                         "candidates": candidates, "consensus_traits": [],
                         "recommended_candidate_id": candidates[0]["candidate_id"] if candidates else None,
                         "selected_candidate_id": None})
    return {"topics": topics, "entities": entities, "sources": sources, "open_questions": [],
            "warnings": ["Mock 离线检索：形象、热度和资料均为演示数据。"]}
