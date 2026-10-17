"""Bounded fetches with per-hop SSRF checks and IP-pinned, verified TLS."""

from concurrent.futures import ThreadPoolExecutor
import ipaddress
from math import isfinite
import socket
from threading import Timer
from http.client import HTTPException
import time
from urllib.parse import quote, urljoin, urlsplit

import certifi
from flask import current_app
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.exceptions import HTTPError

from app.agent.search.base import FetchedResource, validate_result_url
from app.agent.search.providers.mock import mock_resource
from app.agent.search.scope import require_allowed_url
from app.api import AppError

_DNS = ThreadPoolExecutor(max_workers=4, thread_name_prefix="cinecrew-dns")
_REDIRECTS = {301, 302, 303, 307, 308}


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise AppError("FETCH_FAILED", "Resource fetch timed out", 502)
    return remaining


def _public_address(value):
    address = ipaddress.ip_address(value)
    if (not address.is_global or address.is_multicast or address.is_reserved or address.is_loopback
            or address.is_private or address.is_link_local or address.is_unspecified):
        raise AppError("URL_NOT_ALLOWED", "Resource address is not public", 422)
    return str(address)


def _target(url, deadline):
    try:
        validate_result_url(url)
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("Only HTTP(S) is accepted for network fetches")
        host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if port not in {80, 443} or not host or "%" in host:
            raise ValueError("Unsupported host or port")
    except (ValueError, UnicodeError, AttributeError) as error:
        raise AppError("URL_NOT_ALLOWED", "Resource URL is not allowed", 422) from error
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        future = _DNS.submit(socket.getaddrinfo, host, port, type=socket.SOCK_STREAM)
        try:
            answers = future.result(timeout=_remaining(deadline))
        except (TimeoutError, OSError) as error:
            future.cancel()
            raise AppError("FETCH_FAILED", "Resource DNS lookup failed or timed out", 502) from error
        addresses = {_public_address(answer[4][0]) for answer in answers}
        if not addresses:
            raise AppError("FETCH_FAILED", "Resource hostname has no addresses", 502)
        address = sorted(addresses)[0]
    else:
        address = _public_address(str(literal))
    return parsed, host, port, address


def _too_large():
    return AppError("FETCH_FAILED", "Resource exceeds its byte limit", 502, payload={"reason": "size_limit"})


def _abort(connection):
    sock = connection.sock
    if sock is not None:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass


def fetch_resource(url, ctx, *, max_bytes, allowed_types, run_id=None):
    require_allowed_url(url, ctx, run_id)
    mock = (current_app.config.get("MODEL_ADAPTER_MODE") == "mock"
            or current_app.config["AGENT_SEARCH_PROVIDER"] == "mock")
    if mock:
        if not url.startswith("mock://"):
            raise AppError("URL_NOT_ALLOWED", "Mock research cannot issue HTTP requests", 422)
        resource = mock_resource(url)
        if resource.content_type not in allowed_types:
            raise AppError("CONTENT_TYPE_NOT_ALLOWED", "Resource media type is not allowed", 422)
        if len(resource.body) > max_bytes:
            raise _too_large()
        return resource
    timeout = current_app.config["AGENT_SEARCH_TIMEOUT_SEC"]
    if not isinstance(timeout, (int, float)) or not isfinite(timeout) or timeout <= 0:
        raise AppError("FETCH_FAILED", "Resource timeout is not configured correctly", 502)
    deadline = time.monotonic() + timeout
    for hop in range(4):
        parsed, host, port, address = _target(url, deadline)
        options = {"timeout": _remaining(deadline)}
        if parsed.scheme == "https":
            options.update(server_hostname=host, assert_hostname=host,
                           cert_reqs="CERT_REQUIRED", ca_certs=certifi.where())
        connection = (HTTPSConnection if parsed.scheme == "https" else HTTPConnection)(address, port, **options)
        timer = Timer(_remaining(deadline), _abort, args=(connection,))
        timer.daemon = True
        response = None
        timer.start()
        try:
            authority = f"[{host}]" if ":" in host else host
            if parsed.port is not None:
                authority += f":{port}"
            path = quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~")
            if parsed.query:
                path += "?" + quote(parsed.query, safe="/%?:@!$&'()*+,;=-._~")
            connection.request("GET", path, headers={"Host": authority, "User-Agent": "CineCrew/AgentResearch",
                "Accept": ", ".join(sorted(allowed_types)), "Accept-Encoding": "identity", "Connection": "close"},
                preload_content=False, decode_content=False)
            response = connection.getresponse()
            _remaining(deadline)
            if response.status in _REDIRECTS:
                location = response.headers.get("Location")
                if not location or hop == 3:
                    raise AppError("URL_NOT_ALLOWED", "Resource exceeded its redirect limit", 422)
                url = urljoin(url, location)
                continue
            if not 200 <= response.status < 300:
                raise AppError("FETCH_FAILED", "Resource server returned an unsuccessful status", 502)
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type not in allowed_types or response.headers.get("Content-Encoding", "identity").lower() != "identity":
                raise AppError("CONTENT_TYPE_NOT_ALLOWED", "Resource media type or encoding is not allowed", 422)
            declared = response.headers.get("Content-Length")
            if declared is not None and (not declared.isdigit() or int(declared) > max_bytes):
                raise _too_large()
            body = bytearray()
            while True:
                _remaining(deadline)
                chunk = response.read1(min(65536, max_bytes + 1 - len(body)), decode_content=False)
                if not chunk:
                    break
                body.extend(chunk)
                if len(body) > max_bytes:
                    raise _too_large()
            _remaining(deadline)
            return FetchedResource(url, content_type, bytes(body))
        except (HTTPError, HTTPException, OSError, ValueError) as error:
            raise AppError("FETCH_FAILED", "Resource fetch failed or timed out", 502) from error
        finally:
            timer.cancel()
            if response is not None:
                response.close()
            connection.close()
    raise AppError("URL_NOT_ALLOWED", "Resource exceeded its redirect limit", 422)
