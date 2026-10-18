"""Process-local memo for expensive whole-file checks, keyed by file identity.

Delivery views are polled; re-hashing every approved source, master and ZIP on
each read is unbounded I/O for real films. A file that is replaced, rewritten
or truncated changes its stat identity, so a hit can only return the result
computed for exactly these bytes as far as the filesystem reports.
"""
from collections import OrderedDict
from pathlib import Path
from threading import Lock

from app.services.generation_outputs import digest

_MAX_ENTRIES = 2048
_cache: OrderedDict = OrderedDict()
_lock = Lock()


def _identity(path: Path):
    stat = path.stat()
    return (str(path.resolve()), stat.st_size, stat.st_mtime_ns, getattr(stat, "st_ino", 0))


def memoized(path: Path, check: str, compute):
    """Return compute(path), reusing the result while the file identity is unchanged."""
    key = (_identity(path), check)
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    value = compute(path)
    if _identity(path) != key[0]:
        return value  # The file changed while it was being read; never cache it.
    with _lock:
        _cache[key] = value
        _cache.move_to_end(key)
        while len(_cache) > _MAX_ENTRIES:
            _cache.popitem(last=False)
    return value


def cached_digest(path: Path) -> str:
    return memoized(path, "sha256", digest)


def clear():
    with _lock:
        _cache.clear()
