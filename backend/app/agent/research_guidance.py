"""Bounded structural examples, never a substitute for observed research evidence."""


def research_needs_guidance():
    return {"field": "research_needs", "example_scope": "brief fragment; replace the teaching text",
        "example": {"research_needs": [{"query": "需要核实的用户概念", "reason": "该概念的实际外观影响创作决策"}]},
        "rules": ["Each entry is an object with query (1..200 chars) and reason (1..300 chars), not a string.",
                  "Describe what needs research; this field does not assert that research succeeded."],
        "schema_resource": {"name": "plan-review", "path": "resources/workspace/brief.schema.json"}}


def dossier_guidance():
    return {"field": "research_dossier", "example_scope": "valid empty evidence structure, not researched facts",
        "example": {"topics": [], "entities": [], "sources": [], "open_questions": [],
                    "warnings": ["结构示例：尚无已验证来源；不能作为研究完成的证据。"],
                    "stats": {"web_searches": 0, "image_searches": 0, "pages_fetched": 0, "references_downloaded": 0}},
        "rules": ["Use the full schema for Topic, Source and Candidate fields; do not invent IDs, URLs or facts.",
                  "Sources must match successful receipts in this Run; candidates require a downloaded reference and its visual analysis for the same entity.",
                  "Each open_question option_id must equal a candidate_id of ONE entity, and image_artifact_id must equal that candidate's reference_id.",
                  "Without verified candidates, leave candidate questions empty, retain warnings and return limitations to Producer; Producer may ask_user.",
                  "Stats are recomputed by the server; this example neither writes evidence nor bypasses validation."],
        "schema_resource": {"name": "plan-review", "path": "resources/workspace/research_dossier.schema.json"}}
