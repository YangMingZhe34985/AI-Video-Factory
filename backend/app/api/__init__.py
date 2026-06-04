from http import HTTPStatus

from flask import jsonify, request
from flask_jwt_extended import verify_jwt_in_request
from pydantic import ValidationError
from werkzeug.exceptions import HTTPException


class AppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = HTTPStatus.BAD_REQUEST,
        payload: dict | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.payload = payload or {}


def api_success(data=None, status_code: int = HTTPStatus.OK):
    return jsonify({"success": True, "data": data or {}}), status_code


def api_error(
    code: str,
    message: str,
    status_code: int = HTTPStatus.BAD_REQUEST,
    payload: dict | None = None,
):
    body = {"success": False, "error": {"code": code, "message": message}}
    if payload:
        body["error"]["details"] = payload
    return jsonify(body), status_code


def register_error_handlers(app):
    @app.errorhandler(AppError)
    def handle_app_error(error: AppError):
        return api_error(
            error.code, error.message, error.status_code, payload=error.payload
        )

    @app.errorhandler(ValidationError)
    def handle_validation_error(error: ValidationError):
        return api_error(
            "INVALID_INPUT",
            "Invalid request payload",
            HTTPStatus.UNPROCESSABLE_ENTITY,
            payload={"fields": error.errors()},
        )

    @app.errorhandler(HTTPException)
    def handle_http_error(error: HTTPException):
        code = "INVALID_INPUT" if error.code and error.code < 500 else "INTERNAL_ERROR"
        return api_error(code, error.description, error.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected_error(error: Exception):
        app.logger.exception("Unhandled error: %s", error)
        return api_error(
            "INTERNAL_ERROR",
            "Internal server error",
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )


def register_auth_handlers(app, jwt):
    @jwt.unauthorized_loader
    def handle_missing_token(reason):
        return api_error("AUTH_REQUIRED", reason, HTTPStatus.UNAUTHORIZED)

    @jwt.invalid_token_loader
    def handle_invalid_token(reason):
        return api_error("INVALID_TOKEN", reason, HTTPStatus.UNAUTHORIZED)

    @jwt.expired_token_loader
    def handle_expired_token(jwt_header, jwt_payload):
        return api_error("TOKEN_EXPIRED", "Token has expired", HTTPStatus.UNAUTHORIZED)

    @jwt.revoked_token_loader
    def handle_revoked_token(jwt_header, jwt_payload):
        return api_error("TOKEN_REVOKED", "Token has been revoked", HTTPStatus.UNAUTHORIZED)

    @jwt.needs_fresh_token_loader
    def handle_fresh_token_required(jwt_header, jwt_payload):
        return api_error("FRESH_TOKEN_REQUIRED", "Fresh token required", HTTPStatus.UNAUTHORIZED)

    @app.before_request
    def require_jwt_for_api():
        if not app.config.get("API_AUTH_REQUIRED", True):
            return None
        if request.method == "OPTIONS":
            return None
        path = request.path.rstrip("/") or "/"
        if not path.startswith("/api"):
            return None
        if path == "/api/health":
            return None
        if path.startswith("/api/auth"):
            return None
        if path.startswith("/api/jobs/") and path.endswith("/stream"):
            return None
        if path.startswith("/api/artifacts/") and (
            path.endswith("/download") or path.endswith("/preview")
        ):
            return None
        verify_jwt_in_request()
        return None


def register_blueprints(app):
    from .artifacts import bp as artifacts_bp
    from .auth import bp as auth_bp
    from .dashboard import bp as dashboard_bp
    from .dashboard import health_bp
    from .jobs import bp as jobs_bp
    from .models import bp as models_bp
    from .prompts import bp as prompts_bp
    from .prompts import global_bp as global_prompts_bp
    from .series import bp as series_bp
    from .uploads import bp as uploads_bp
    from .workflow import bp as workflow_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(health_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(jobs_bp)
    app.register_blueprint(global_prompts_bp)
    app.register_blueprint(prompts_bp)
    app.register_blueprint(models_bp)
    app.register_blueprint(artifacts_bp)
    app.register_blueprint(series_bp)
    app.register_blueprint(workflow_bp)
    app.register_blueprint(uploads_bp)
