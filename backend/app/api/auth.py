from http import HTTPStatus

from flask import Blueprint, request
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    get_jwt_identity,
    jwt_required,
)

from app.api import api_success, AppError
from app.extensions import db
from app.models.user import User

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@bp.post("/register")
def register():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    email = (data.get("email") or "").strip()
    password = (data.get("password") or "").strip()

    if not username or len(username) < 2:
        raise AppError("INVALID_INPUT", "Username must be at least 2 characters")
    if not password or len(password) < 6:
        raise AppError("INVALID_INPUT", "Password must be at least 6 characters")

    if User.query.filter_by(username=username).first():
        raise AppError("USERNAME_TAKEN", "Username already exists", HTTPStatus.CONFLICT)
    if email and User.query.filter_by(email=email).first():
        raise AppError("EMAIL_TAKEN", "Email already exists", HTTPStatus.CONFLICT)

    user = User(username=username, email=email or None)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    access_token = create_access_token(identity=user.user_id)
    refresh_token = create_refresh_token(identity=user.user_id)

    return api_success({
        "user": user.to_dict(),
        "access_token": access_token,
        "refresh_token": refresh_token,
    }, HTTPStatus.CREATED)


@bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()

    if not username or not password:
        raise AppError("INVALID_INPUT", "Username and password are required")

    user = User.query.filter_by(username=username).first()
    if not user or not user.check_password(password):
        raise AppError("INVALID_CREDENTIALS", "Invalid username or password", HTTPStatus.UNAUTHORIZED)
    if not user.is_active:
        raise AppError("USER_INACTIVE", "Account is disabled", HTTPStatus.FORBIDDEN)

    access_token = create_access_token(identity=user.user_id)
    refresh_token = create_refresh_token(identity=user.user_id)

    return api_success({
        "user": user.to_dict(),
        "access_token": access_token,
        "refresh_token": refresh_token,
    })


@bp.get("/me")
@jwt_required()
def me():
    user_id = get_jwt_identity()
    user = User.query.filter_by(user_id=user_id).first()
    if not user:
        raise AppError("USER_NOT_FOUND", "User not found", HTTPStatus.NOT_FOUND)
    return api_success({"user": user.to_dict()})


@bp.post("/refresh")
@jwt_required(refresh=True)
def refresh():
    user_id = get_jwt_identity()
    user = User.query.filter_by(user_id=user_id).first()
    if not user or not user.is_active:
        raise AppError("USER_NOT_FOUND", "User not found or inactive", HTTPStatus.NOT_FOUND)
    access_token = create_access_token(identity=user.user_id)
    return api_success({"access_token": access_token})