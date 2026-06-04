from app.api import AppError
from app.extensions import db
from app.models.series import Series
from app.models.template import Template
from app.utils.time_utils import utc_now


class SeriesService:

    @staticmethod
    def ensure_default_series() -> Series:
        default = Series.query.filter_by(series_id="default").first()
        if not default:
            default = Series(
                series_id="default",
                name="Default Series",
                description="Default series for uncategorized templates",
                is_default=True,
            )
            db.session.add(default)
            db.session.commit()
        return default

    @staticmethod
    def list_series() -> list[Series]:
        return Series.query.order_by(Series.created_at.asc()).all()

    @staticmethod
    def get_series(series_id: str) -> Series:
        s = Series.query.filter_by(series_id=series_id).first()
        if not s:
            raise AppError("SERIES_NOT_FOUND", "Series not found", 404)
        return s

    @staticmethod
    def create_series(data: dict) -> Series:
        series_id = data.get("series_id", "").strip()
        if not series_id:
            raise AppError("INVALID_INPUT", "series_id is required", 400)
        if Series.query.filter_by(series_id=series_id).first():
            raise AppError("SERIES_EXISTS", "Series with this ID already exists", 409)
        s = Series(
            series_id=series_id,
            name=data.get("name", series_id),
            description=data.get("description"),
            is_default=False,
        )
        db.session.add(s)
        db.session.commit()
        return s

    @staticmethod
    def update_series(series_id: str, data: dict) -> Series:
        s = SeriesService.get_series(series_id)
        if "name" in data and data["name"]:
            s.name = data["name"]
        if "description" in data:
            s.description = data["description"]
        db.session.commit()
        return s

    @staticmethod
    def delete_series(series_id: str) -> None:
        s = SeriesService.get_series(series_id)
        if s.is_default:
            raise AppError("CANNOT_DELETE_DEFAULT", "Cannot delete the default Series", 400)
        template_count = Template.query.filter_by(series=series_id).count()
        if template_count > 0:
            raise AppError(
                "SERIES_HAS_TEMPLATES",
                f"Cannot delete series with {template_count} template(s). Move or delete templates first.",
                400,
            )
        db.session.delete(s)
        db.session.commit()

    @staticmethod
    def move_template(template_id: str, target_series_id: str) -> Template:
        template = Template.query.filter_by(template_id=template_id).first()
        if not template:
            raise AppError("TEMPLATE_NOT_FOUND", "Template not found", 404)
        # Ensure target series exists
        SeriesService.get_series(target_series_id)
        template.series = target_series_id
        db.session.commit()
        return template

    @staticmethod
    def enrich_template(template: Template) -> dict:
        """Return template dict enriched with series_name."""
        data = template.to_dict()
        series_id = template.series or "default"
        s = Series.query.filter_by(series_id=series_id).first()
        data["series_id"] = series_id
        data["series_name"] = s.name if s else series_id
        return data

    @staticmethod
    def enrich_templates(templates: list[Template]) -> list[dict]:
        # Batch load series names
        series_ids = {t.series or "default" for t in templates}
        series_map = {
            s.series_id: s.name
            for s in Series.query.filter(Series.series_id.in_(series_ids)).all()
        }
        result = []
        for t in templates:
            data = t.to_dict()
            sid = t.series or "default"
            data["series_id"] = sid
            data["series_name"] = series_map.get(sid, sid)
            result.append(data)
        return result
