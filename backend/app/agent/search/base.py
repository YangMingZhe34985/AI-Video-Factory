"""Provider-neutral search contracts; result bodies are untrusted data."""

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


def validate_result_url(value):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 4096 or any(ord(char) < 33 or char == "\\" for char in value):
        raise ValueError("Invalid resource URL")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https", "mock"} or not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise ValueError("Only uncredentialed HTTP(S) or Mock resource URLs are accepted")
    if parsed.port is not None and parsed.port not in {80, 443}:
        raise ValueError("Only HTTP(S) ports are accepted")
    return value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class WebResult(StrictModel):
    result_id: str = Field(min_length=1, max_length=80)
    rank: int = Field(ge=1)
    title: str = Field(max_length=300)
    url: str = Field(min_length=1, max_length=4096)
    site: str = Field(max_length=300)
    snippet: str = Field(max_length=1000)
    published_at: str | None = None

    _valid_url = field_validator("url")(validate_result_url)


class ImageResult(StrictModel):
    result_id: str = Field(min_length=1, max_length=80)
    rank: int = Field(ge=1)
    image_url: str = Field(min_length=1, max_length=4096)
    thumbnail_url: str | None = Field(default=None, max_length=4096)
    source_page_url: str = Field(min_length=1, max_length=4096)
    title: str = Field(max_length=300)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    license_hint: str | None = Field(default=None, max_length=300)

    _valid_urls = field_validator("image_url", "thumbnail_url", "source_page_url")(validate_result_url)


@dataclass(frozen=True)
class FetchedResource:
    final_url: str
    content_type: str
    body: bytes


class SearchProvider(Protocol):
    name: str

    def web_search(self, query: str, *, locale: str, freshness: str, max_results: int) -> list[WebResult]: ...

    def image_search(self, query: str, *, max_results: int, safe: bool) -> list[ImageResult]: ...
