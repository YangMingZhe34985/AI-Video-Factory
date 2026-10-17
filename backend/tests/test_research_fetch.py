"""B6 transport tests use in-memory connections and never contact a network."""

import socket
import time

import pytest

from app.agent.search import fetch
from app.api import AppError
from tests.test_research_search import ctx, research_run


class Response:
    def __init__(self, body=b"hello", status=200, headers=None):
        self.body = body
        self.status = status
        self.headers = {"Content-Type": "text/plain", **(headers or {})}
        self.closed = False

    def read1(self, amount, decode_content=False):
        part, self.body = self.body[:amount], self.body[amount:]
        return part

    def close(self):
        self.closed = True


class Connection:
    def __init__(self, address, port, response, **options):
        self.address, self.port, self.options = address, port, options
        self.response, self.request_args = response, None
        self.sock = None
        self.closed = False

    def request(self, *args, **kwargs):
        self.request_args = (args, kwargs)

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


def network(app_ctx, monkeypatch, responses, addresses=None):
    app_ctx.config.update(MODEL_ADAPTER_MODE="real", AGENT_SEARCH_PROVIDER="future-provider")
    calls, dns = [], []
    def resolve(host, port, **kwargs):
        dns.append(host)
        values = (addresses or {}).get(host, ["93.184.216.34"])
        return [(socket.AF_INET6 if ":" in value else socket.AF_INET, socket.SOCK_STREAM, 6, "", (value, port)) for value in values]
    def connect(address, port, **kwargs):
        connection = Connection(address, port, responses[len(calls)], **kwargs)
        calls.append(connection)
        return connection
    monkeypatch.setattr(fetch.socket, "getaddrinfo", resolve)
    monkeypatch.setattr(fetch, "HTTPConnection", connect)
    monkeypatch.setattr(fetch, "HTTPSConnection", connect)
    return calls, dns


def read(url, run, **kwargs):
    return fetch.fetch_resource(url, ctx(run), max_bytes=kwargs.get("max_bytes", 10000),
                                allowed_types=kwargs.get("allowed_types", {"text/plain", "text/html"}))


def test_https_pins_resolved_ip_and_keeps_verified_original_tls_host(app_ctx, monkeypatch):
    url = "https://public.example/hello?q=one"
    run = research_run(url)
    calls, dns = network(app_ctx, monkeypatch, [Response()])
    result = read(url, run)
    assert result.body == b"hello" and result.final_url == url
    assert dns == ["public.example"]
    connection = calls[0]
    assert connection.address == "93.184.216.34"
    assert connection.options["server_hostname"] == connection.options["assert_hostname"] == "public.example"
    assert connection.options["cert_reqs"] == "CERT_REQUIRED" and connection.options["ca_certs"]
    args, kwargs = connection.request_args
    assert args == ("GET", "/hello?q=one")
    assert kwargs["headers"]["Host"] == "public.example"
    assert kwargs["headers"]["User-Agent"].startswith("CineCrew")
    assert "Cookie" not in kwargs["headers"] and "Authorization" not in kwargs["headers"]
    assert kwargs["decode_content"] is False and kwargs["preload_content"] is False
    assert connection.closed and connection.response.closed


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "224.0.0.1", "240.0.0.1", "::1", "fc00::1", "fe80::1", "::ffff:127.0.0.1"])
def test_resolved_nonpublic_addresses_are_rejected_before_connection(app_ctx, monkeypatch, address):
    url = "http://public.example/"
    run = research_run(url)
    calls, dns = network(app_ctx, monkeypatch, [], {"public.example": [address]})
    with pytest.raises(AppError) as stopped:
        read(url, run)
    assert stopped.value.code == "URL_NOT_ALLOWED"
    assert calls == []


def test_mixed_public_private_dns_answers_are_all_rejected(app_ctx, monkeypatch):
    url = "https://public.example/"
    run = research_run(url)
    calls, dns = network(app_ctx, monkeypatch, [], {"public.example": ["93.184.216.34", "10.0.0.1"]})
    with pytest.raises(AppError) as stopped:
        read(url, run)
    assert stopped.value.code == "URL_NOT_ALLOWED"
    assert not calls


def test_redirect_revalidates_dns_but_does_not_require_result_allowlist(app_ctx, monkeypatch):
    url = "https://one.example/"
    run = research_run(url)
    calls, dns = network(app_ctx, monkeypatch, [Response(status=302, headers={"Location": "https://two.example/page"}), Response()],
        {"one.example": ["93.184.216.34"], "two.example": ["1.1.1.1"]})
    assert read(url, run).final_url == "https://two.example/page"
    assert dns == ["one.example", "two.example"]
    assert [connection.address for connection in calls] == ["93.184.216.34", "1.1.1.1"]
    assert all(connection.closed for connection in calls)


def test_redirect_to_private_or_rebound_host_is_blocked(app_ctx, monkeypatch):
    url = "https://one.example/"
    run = research_run(url)
    calls, dns = network(app_ctx, monkeypatch, [Response(status=302, headers={"Location": "http://internal.example/private"})],
        {"one.example": ["93.184.216.34"], "internal.example": ["127.0.0.1"]})
    with pytest.raises(AppError) as stopped:
        read(url, run)
    assert stopped.value.code == "URL_NOT_ALLOWED" and len(calls) == 1
    assert dns == ["one.example", "internal.example"]


def test_redirect_limit_is_three(app_ctx, monkeypatch):
    url = "https://one.example/"
    run = research_run(url)
    calls, dns = network(app_ctx, monkeypatch, [Response(status=302, headers={"Location": "/again"}) for _ in range(4)])
    with pytest.raises(AppError) as stopped:
        read(url, run)
    assert stopped.value.code == "URL_NOT_ALLOWED"
    assert len(calls) == 4


@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://2130706433/", "http://public.example:8080/", "http://user:secret@public.example/", "file:///etc/passwd"])
def test_unsafe_literal_scheme_port_or_credentials_are_blocked(app_ctx, monkeypatch, url):
    run = research_run(url)
    calls, dns = network(app_ctx, monkeypatch, [], {"2130706433": ["127.0.0.1"]})
    with pytest.raises(AppError) as stopped:
        read(url, run)
    assert stopped.value.code == "URL_NOT_ALLOWED"
    assert not calls


@pytest.mark.parametrize("response,code", [
    (Response(headers={"Content-Type": "application/json"}), "CONTENT_TYPE_NOT_ALLOWED"),
    (Response(headers={"Content-Encoding": "gzip"}), "CONTENT_TYPE_NOT_ALLOWED"),
    (Response(headers={"Content-Length": "10001"}), "FETCH_FAILED"),
    (Response(body=b"x" * 10001), "FETCH_FAILED"),
    (Response(status=500), "FETCH_FAILED"),
])
def test_content_and_byte_limits_are_enforced_while_streaming(app_ctx, monkeypatch, response, code):
    url = "https://one.example/"
    run = research_run(url)
    calls, _ = network(app_ctx, monkeypatch, [response])
    with pytest.raises(AppError) as stopped:
        read(url, run)
    assert stopped.value.code == code
    assert calls[0].closed and response.closed


def test_total_timeout_closes_a_slow_response(app_ctx, monkeypatch):
    class SlowResponse(Response):
        def read1(self, amount, decode_content=False):
            time.sleep(0.05)
            return super().read1(amount, decode_content)
    url = "https://one.example/"
    run = research_run(url)
    calls, _ = network(app_ctx, monkeypatch, [SlowResponse()])
    app_ctx.config["AGENT_SEARCH_TIMEOUT_SEC"] = 0.02
    with pytest.raises(AppError) as stopped:
        read(url, run)
    assert stopped.value.code == "FETCH_FAILED"
    assert calls[0].closed


def test_dns_timeout_is_bounded_without_opening_connection(app_ctx, monkeypatch):
    url = "https://one.example/"
    run = research_run(url)
    calls, _ = network(app_ctx, monkeypatch, [])
    app_ctx.config["AGENT_SEARCH_TIMEOUT_SEC"] = 0.01
    def slow_dns(*a, **k):
        time.sleep(0.05)
        return []
    monkeypatch.setattr(fetch.socket, "getaddrinfo", slow_dns)
    with pytest.raises(AppError) as stopped:
        read(url, run)
    assert stopped.value.code == "FETCH_FAILED"
    assert not calls
