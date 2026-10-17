"""Fetch allowlisted pages as bounded, untrusted plain text."""

from html.parser import HTMLParser

from flask import current_app
from pydantic import Field

from app.agent.search.base import StrictModel
from app.agent.search.fetch import fetch_resource
from app.agent.search.scope import require_run, reserve
from app.skills.permissions import EXTERNAL, RESEARCH, SYSTEM
from app.skills.spec import ToolSpec
from app.utils.time_utils import utc_now


class FetchPageInput(StrictModel):
    run_id: str = Field(min_length=1, max_length=80)
    url: str = Field(min_length=1, max_length=4096)
    max_chars: int = Field(default=8000, ge=500, le=20000, strict=True)


class FetchPageOutput(StrictModel):
    url: str
    final_url: str
    title: str = Field(max_length=300)
    text: str = Field(max_length=20000)
    content_type: str
    truncated: bool
    fetched_at: str


class PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.in_title = False
        self.title, self.text = [], []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "template"}:
            self.hidden += 1
        if tag == "title":
            self.in_title = True

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "template"}:
            self.hidden = max(0, self.hidden - 1)
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if not self.hidden:
            self.text.append(data)
            if self.in_title:
                self.title.append(data)


def run(data, ctx):
    require_run(ctx, data.run_id)
    reserve(ctx, {"fetch_page"}, "AGENT_RESEARCH_MAX_FETCHES")
    resource = fetch_resource(data.url, ctx, run_id=data.run_id,
        max_bytes=current_app.config["AGENT_FETCH_MAX_BYTES"], allowed_types={"text/html", "text/plain"})
    text, title = resource.body.decode("utf-8", errors="replace"), ""
    if resource.content_type == "text/html":
        parser = PageText()
        parser.feed(text)
        text, title = " ".join(parser.text), " ".join(parser.title)
    text = " ".join(text.split())
    return FetchPageOutput(url=data.url, final_url=resource.final_url, title=title[:300],
        text=text[:data.max_chars], content_type=resource.content_type, truncated=len(text) > data.max_chars,
        fetched_at=utc_now().isoformat())


SPEC = ToolSpec(name="fetch_page", description="Read an allowlisted page as untrusted text",
    input_model=FetchPageInput, output_model=FetchPageOutput, handler=run, permission=EXTERNAL,
    allowed_roles=frozenset({RESEARCH, SYSTEM}), max_retries=0)
