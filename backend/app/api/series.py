from http import HTTPStatus

from flask import Blueprint, request

from app.api import api_success
from app.services.series_service import SeriesService


bp = Blueprint("series", __name__, url_prefix="/api/series")


@bp.get("")
def list_series():
    series_list = SeriesService.list_series()
    return api_success({"series": [s.to_dict() for s in series_list]})


@bp.post("")
def create_series():
    data = request.get_json(silent=True) or {}
    s = SeriesService.create_series(data)
    return api_success(s.to_dict(), HTTPStatus.CREATED)


@bp.get("/<series_id>")
def get_series(series_id: str):
    s = SeriesService.get_series(series_id)
    return api_success(s.to_dict())


@bp.put("/<series_id>")
def update_series(series_id: str):
    data = request.get_json(silent=True) or {}
    s = SeriesService.update_series(series_id, data)
    return api_success(s.to_dict())


@bp.delete("/<series_id>")
def delete_series(series_id: str):
    SeriesService.delete_series(series_id)
    return api_success({"deleted": series_id})
