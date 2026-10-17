"""Research contracts and provenance checks; model output never grants authority."""

from typing import Literal

from flask import current_app
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.api import AppError
from app.agent.clarify import Question
from app.models import AgentRun, Artifact, ToolInvocation


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ImageQuery(StrictModel):
    entity: str = Field(min_length=1, max_length=80)
    query: str = Field(min_length=1, max_length=200)


class ResearchPlan(StrictModel):
    web_queries: list[str] = Field(default_factory=list, max_length=4)
    image_queries: list[ImageQuery] = Field(default_factory=list, max_length=4)


class ImageSelection(StrictModel):
    entity: str = Field(min_length=1, max_length=80)
    result_ids: list[str] = Field(min_length=1, max_length=4)


class ResearchSelection(StrictModel):
    page_ids: list[str] = Field(default_factory=list, max_length=6)
    images: list[ImageSelection] = Field(default_factory=list, max_length=4)


class KeyFact(StrictModel):
    fact: str = Field(min_length=1, max_length=300)
    source_ids: list[str] = Field(min_length=1, max_length=40)


class Topic(StrictModel):
    topic_id: str = Field(min_length=1, max_length=40)
    query: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=1500)
    key_facts: list[KeyFact] = Field(default_factory=list, max_length=10)
    confidence: float = Field(ge=0, le=1)


class Candidate(StrictModel):
    candidate_id: str = Field(min_length=1, max_length=40)
    reference_id: str = Field(min_length=1, max_length=80)
    source_id: str = Field(min_length=1, max_length=40)
    traits: list[str] = Field(default_factory=list, max_length=12)
    popularity_hint: Literal["high", "medium", "low"] | None = None
    why: str = Field(max_length=300)


class VisualEntity(StrictModel):
    entity_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,24}$")
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(max_length=500)
    candidates: list[Candidate] = Field(default_factory=list, max_length=4)
    consensus_traits: list[str] = Field(default_factory=list, max_length=12)
    recommended_candidate_id: str | None = None
    selected_candidate_id: str | None = None


class Source(StrictModel):
    source_id: str = Field(min_length=1, max_length=40)
    kind: Literal["web", "image"]
    url: str
    title: str = Field(max_length=300)
    site: str
    published_at: str | None = None
    retrieved_at: str


class ResearchStats(StrictModel):
    web_searches: int = Field(ge=0, default=0)
    image_searches: int = Field(ge=0, default=0)
    pages_fetched: int = Field(ge=0, default=0)
    references_downloaded: int = Field(ge=0, default=0)


class ResearchDossier(StrictModel):
    topics: list[Topic] = Field(default_factory=list, max_length=6)
    entities: list[VisualEntity] = Field(default_factory=list, max_length=8)
    sources: list[Source] = Field(default_factory=list, max_length=40)
    open_questions: list[Question] = Field(default_factory=list, max_length=3)
    warnings: list[str] = Field(default_factory=list, max_length=10)
    stats: ResearchStats = Field(default_factory=ResearchStats)


# The draft admits missing citations so the final validator can drop unsupported
# facts as required by B.7, rather than discarding otherwise usable research.
class DraftFact(KeyFact):
    source_ids: list[str] = Field(default_factory=list, max_length=40)


class DraftTopic(Topic):
    key_facts: list[DraftFact] = Field(default_factory=list, max_length=10)


class DossierDraft(ResearchDossier):
    topics: list[DraftTopic] = Field(default_factory=list, max_length=6)


def invalid(message):
    return AppError("INVALID_RESEARCH_DOSSIER", message, 422)


def validate_research_plan(raw):
    plan = ResearchPlan.model_validate(raw)
    queries = [*plan.web_queries, *(item.query for item in plan.image_queries)]
    if not queries or any(not 1 <= len(query.strip()) <= 200 for query in queries):
        raise invalid("Research needs at least one bounded query")
    if len(queries) > current_app.config["AGENT_RESEARCH_MAX_QUERIES"]:
        raise AppError("RESEARCH_LIMIT_REACHED", "Research plan exceeds the query limit", 409)
    if len(set(plan.web_queries)) != len(plan.web_queries) or len({item.entity for item in plan.image_queries}) != len(plan.image_queries):
        raise invalid("Research queries and entity groups must be unique")
    return plan.model_dump(mode="json")


def validate_selection(raw, state):
    selection = ResearchSelection.model_validate(raw)
    hits = {item["result_id"]: item for item in state["research_hits"]}
    if len(selection.page_ids) > current_app.config["AGENT_RESEARCH_MAX_FETCHES"]:
        raise AppError("RESEARCH_LIMIT_REACHED", "Research selection exceeds the page limit", 409)
    if len(set(selection.page_ids)) != len(selection.page_ids):
        raise invalid("A page cannot be selected twice")
    for result_id in selection.page_ids:
        if result_id not in hits or hits[result_id]["kind"] != "web":
            raise invalid("Page selection must name an observed web result ID")
    entities = set()
    for group in selection.images:
        if group.entity in entities or len(set(group.result_ids)) != len(group.result_ids):
            raise invalid("Image selections must be unique within an entity")
        entities.add(group.entity)
        for result_id in group.result_ids:
            if (result_id not in hits or hits[result_id]["kind"] != "image"
                    or hits[result_id]["entity"] != group.entity):
                raise invalid("Image selection must name an observed result for this entity")
    if sum(len(group.result_ids) for group in selection.images) > current_app.config["AGENT_MAX_REFERENCE_DOWNLOADS"]:
        raise AppError("RESEARCH_LIMIT_REACHED", "Research selection exceeds the reference limit", 409)
    return selection.model_dump(mode="json")


def sources_for(state):
    from urllib.parse import urlsplit
    sources = {}
    for hit in state.get("research_hits", []):
        url = hit["url"] if hit["kind"] == "web" else hit["source_page_url"]
        sources[hit["result_id"]] = {
            "source_id": hit["result_id"], "kind": hit["kind"], "url": url,
            "title": hit["title"], "site": hit.get("site") or urlsplit(url).hostname or "Mock",
            "published_at": hit.get("published_at"), "retrieved_at": hit["fetched_at"],
        }
    return sources


def analysis_traits(analysis):
    return list(dict.fromkeys([*(item["appearance"] for item in analysis.get("subjects", [])),
                              *([analysis["style"]] if analysis.get("style") else [])]))[:12]


def research_stats(run_id):
    names = {"web_search": "web_searches", "image_search": "image_searches", "fetch_page": "pages_fetched"}
    stats = ResearchStats().model_dump()
    for invocation in ToolInvocation.query.filter_by(budget_scope=run_id):
        if invocation.tool_name in names and invocation.status != "rejected":
            stats[names[invocation.tool_name]] += invocation.attempt
    stats["references_downloaded"] = Artifact.query.filter(
        Artifact.artifact_type == "agent_reference_image",
        Artifact.meta["reference"]["run_id"].as_string() == run_id,
    ).count()
    return stats


def validate_dossier(raw, state):
    try:
        dossier = DossierDraft.model_validate(raw).model_dump(mode="json")
    except ValidationError as error:
        raise invalid("Research dossier schema is invalid") from error
    canonical = sources_for(state)
    sources = {}
    for source in dossier["sources"]:
        source_id = source["source_id"]
        expected = canonical.get(source_id)
        if (not expected or source_id in sources or source["url"] != expected["url"]
                or source["kind"] != expected["kind"]):
            raise invalid("Research sources must match observed results")
        sources[source_id] = expected
    dossier["sources"] = list(sources.values())
    seen_topics, seen_entities = set(), set()
    discarded = False
    for topic in dossier["topics"]:
        if topic["topic_id"] in seen_topics:
            raise invalid("Duplicate research topic")
        seen_topics.add(topic["topic_id"])
        facts = []
        for fact in topic["key_facts"]:
            if not fact["source_ids"]:
                discarded = True
                continue
            if not set(fact["source_ids"]) <= sources.keys():
                raise invalid("Research fact refers to an unknown source")
            facts.append(fact)
        topic["key_facts"] = facts
    owner = AgentRun.query.filter_by(run_id=state["run_id"]).one()
    observations = {(item["entity"], item["source_id"], item["reference_id"])
                    for item in state.get("research_images", [])}
    analyses = state.get("research_analyses", {})
    for entity in dossier["entities"]:
        if entity["entity_id"] in seen_entities:
            raise invalid("Duplicate research entity")
        seen_entities.add(entity["entity_id"])
        ids = [item["candidate_id"] for item in entity["candidates"]]
        if len(ids) != len(set(ids)):
            raise invalid("Duplicate visual candidate")
        for field in ("recommended_candidate_id", "selected_candidate_id"):
            if entity[field] is not None and entity[field] not in ids:
                raise invalid("Candidate selection must belong to its entity")
        for candidate in entity["candidates"]:
            ref_id, source_id = candidate["reference_id"], candidate["source_id"]
            artifact = Artifact.query.filter_by(artifact_id=ref_id).first()
            if (source_id not in sources or sources[source_id]["kind"] != "image"
                    or (entity["name"], source_id, ref_id) not in observations or ref_id not in analyses
                    or not artifact or artifact.artifact_type != "agent_reference_image"
                    or (artifact.meta or {}).get("reference", {}).get("run_id") != owner.run_id
                    or (artifact.job.config or {}).get("agent_upload_owner") != owner.owner_id):
                raise invalid("A candidate must be an analyzed reference downloaded for this run and entity")
            candidate["traits"] = analysis_traits(analyses[ref_id])
    for question in dossier["open_questions"]:
        matches = []
        for entity in dossier["entities"]:
            candidates = {item["candidate_id"]: item["reference_id"] for item in entity["candidates"]}
            if all(option["option_id"] in candidates and option["image_artifact_id"] == candidates[option["option_id"]]
                   for option in question["options"]):
                matches.append(entity)
        if len(matches) != 1:
            raise invalid("Research question images must match candidates of exactly one entity")
    warnings = [*state.get("research_warnings", []), *dossier["warnings"]]
    if discarded:
        warnings.append("已丢弃没有来源引用的事实。")
    dossier["warnings"] = list(dict.fromkeys(warnings))[:10]
    dossier["stats"] = research_stats(state["run_id"])
    return ResearchDossier.model_validate(dossier).model_dump(mode="json")
