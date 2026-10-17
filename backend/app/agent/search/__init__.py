"""Resolve the configured provider without exposing credentials to Skills."""

from flask import current_app

from app.api import AppError


def get_search_provider():
    from app.agent.search.providers.mock import MockSearchProvider
    if current_app.config.get("MODEL_ADAPTER_MODE") == "mock" or current_app.config["AGENT_SEARCH_PROVIDER"] == "mock":
        return MockSearchProvider()
    raise AppError("SEARCH_PROVIDER_NOT_CONFIGURED", "The selected search provider is not configured", 503)
