"""A small in-process rate limiter for the unauthenticated endpoints.

Password reset and token lookup are the only routes anyone can call without
credentials, which makes them the only ones worth flooding: to mail-bomb a
customer, or to grind through token guesses.

**This counts per process.** The deployment runs a single uvicorn worker
(``WEB_CONCURRENCY=1``), so today that is the whole application. If workers
are ever scaled up, the effective limit multiplies by the worker count and
this should move to the database or a shared cache — it is not a correctness
bug, but it stops being the number written in the config.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

# key -> timestamps of recent hits, oldest first
_hits: dict[str, deque[float]] = defaultdict(deque)

# Sweep idle keys occasionally so a long-running process does not accumulate
# one deque per address ever seen.
_last_sweep = 0.0
_SWEEP_EVERY = 600.0


def _sweep(now: float, window: float) -> None:
    global _last_sweep
    if now - _last_sweep < _SWEEP_EVERY:
        return
    _last_sweep = now
    for key in [k for k, v in _hits.items() if not v or now - v[-1] > window]:
        _hits.pop(key, None)


def hit(key: str, *, limit: int, window_seconds: int) -> bool:
    """Record an attempt. Returns False when ``key`` is over its limit."""
    now = time.monotonic()
    _sweep(now, window_seconds)
    bucket = _hits[key]
    while bucket and now - bucket[0] > window_seconds:
        bucket.popleft()
    if len(bucket) >= limit:
        return False
    bucket.append(now)
    return True


def enforce(key: str, *, limit: int, window_seconds: int, detail: str) -> None:
    if not hit(key, limit=limit, window_seconds=window_seconds):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail)


def client_ip(request: Request) -> str:
    """Best-effort client address.

    Render terminates TLS and forwards, so the socket peer is the proxy;
    ``X-Forwarded-For``'s first entry is the caller. That header is
    caller-controlled and trivially spoofed, which is why it is only ever used
    to *spread* traffic across buckets, never to grant anything.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def reset() -> None:
    """Clear all buckets. For tests."""
    _hits.clear()
