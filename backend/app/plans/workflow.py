"""Classic-path plans: run the classic workflow under a user's series and template (V.25)."""

from hashlib import sha256

from app.api import AppError
from app.models import Series, Template

# The Agent's private workspace is never a classic-path target (D-066).
INTERNAL_SERIES = frozenset({"agent_studio"})
INTERNAL_TEMPLATES = frozenset({"agent_workspace"})
CONTENT_PROMPT_TYPES = ("t2v", "first_frame_image", "i2v", "r2v_flash", "i2i")
MAX_LISTED_TEMPLATES = 50


def _public_template(template):
    return template.template_id not in INTERNAL_TEMPLATES and (template.series or "default") not in INTERNAL_SERIES


def prompt_summary(template, limit=120):
    from app.services.prompt_service import PromptService
    summary = {}
    for kind in CONTENT_PROMPT_TYPES:
        item = PromptService.get_active_for_template(template, kind)
        if item is not None and (item.content or "").strip():
            summary[kind] = {"version": item.version, "preview": item.content.strip()[:limit]}
    return summary


def catalog(series_id=None, query=None):
    """Public series/template catalog for planning; internal Agent storage is hidden."""
    series = {row.series_id: row for row in Series.query.order_by(Series.series_id).all()
              if row.series_id not in INTERNAL_SERIES}
    if series_id is not None and series_id not in series:
        raise AppError("SERIES_NOT_FOUND", "Series is not available for classic workflows", 404)
    rows = Template.query.order_by(Template.created_at.desc(), Template.id.desc()).all()
    needle = (query or "").casefold()
    groups = {key: [] for key in series if series_id in {None, key}}
    listed = 0
    for template in rows:
        key = template.series or "default"
        if not _public_template(template) or key not in groups or listed >= MAX_LISTED_TEMPLATES:
            continue
        if needle and needle not in f"{template.name}\n{template.description or ''}".casefold():
            continue
        groups[key].append({"template_id": template.template_id, "name": template.name,
                            "description": (template.description or "")[:300],
                            "prompt_types": prompt_summary(template)})
        listed += 1
    return [{"series_id": key, "name": series[key].name, "description": (series[key].description or "")[:300],
             "templates": items} for key, items in groups.items() if items or not needle]


def created_template_id(run_id, node_id):
    """Deterministic ID so a retried node reuses the template it created."""
    return "tpl_v3_" + sha256(f"{run_id}:{node_id}".encode()).hexdigest()[:20]


def resolve_target(target, run_id, node_id):
    """Validate a template target without writing; returns its public description."""
    if not isinstance(target, dict) or set(target) not in ({"template_id"}, {"series_id", "new_template_name"}):
        raise AppError("INVALID_TEMPLATE_TARGET", "template_target needs template_id, or series_id with new_template_name", 422,
                       payload={"field": "inputs.template_target"})
    if "template_id" in target:
        template = Template.query.filter_by(template_id=target["template_id"]).first()
        if template is None or not _public_template(template):
            raise AppError("TEMPLATE_NOT_FOUND", "Template is not available for classic workflows", 404,
                           payload={"field": "inputs.template_target.template_id"})
        series = Series.query.filter_by(series_id=template.series or "default").first()
        return {"mode": "existing", "template_id": template.template_id, "template_name": template.name,
                "series_id": template.series or "default", "series_name": series.name if series else template.series}
    series_id, name = target["series_id"], target["new_template_name"]
    series = Series.query.filter_by(series_id=series_id).first() if isinstance(series_id, str) else None
    if series is None or series.series_id in INTERNAL_SERIES:
        raise AppError("SERIES_NOT_FOUND", "New templates must be created under an existing series", 404,
                       payload={"field": "inputs.template_target.series_id"})
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise AppError("INVALID_TEMPLATE_TARGET", "New template name must contain 1 to 80 characters", 422,
                       payload={"field": "inputs.template_target.new_template_name"})
    template_id = created_template_id(run_id, node_id)
    existing = Template.query.filter_by(series=series.series_id, name=name.strip()).first()
    if existing is not None and existing.template_id != template_id:
        raise AppError("TEMPLATE_NAME_EXISTS", "A template with this name already exists in the series", 409,
                       payload={"field": "inputs.template_target.new_template_name"})
    return {"mode": "new", "template_id": template_id, "template_name": name.strip(),
            "series_id": series.series_id, "series_name": series.name}
