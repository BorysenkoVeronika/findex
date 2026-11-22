"""HTTP retrieval with bounded retries and structured fetch results."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import random
import time
import logging
import httpx

logger = logging.getLogger("findex.crawler")


@dataclass(frozen=True, slots=True)
class FetchResult:
    url: str
    status: int
    content: bytes
    elapsed: float
    content_type: str = ""


def _retry_after(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            return max(0.0, (date - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return 0.0


async def fetch(
    client: httpx.AsyncClient,
    url: str,
    *,
    timeout: float = 10.0,
    attempts: int = 3,
) -> FetchResult:
    """Retry only transient failures; HTTP 4xx (except 429) are final."""
    started = time.perf_counter()
    for attempt in range(max(1, attempts)):
        try:
            async with asyncio.timeout(timeout):
                response = await client.get(url, follow_redirects=False)
            status = response.status_code
            if status != 429 and status < 500:
                return FetchResult(
                    str(response.url),
                    status,
                    response.content,
                    time.perf_counter() - started,
                    response.headers.get("content-type", ""),
                )
            if attempt == max(1, attempts) - 1:
                return FetchResult(
                    str(response.url),
                    status,
                    response.content,
                    time.perf_counter() - started,
                    response.headers.get("content-type", ""),
                )
            backoff = min(8.0, 0.25 * 2**attempt) + random.uniform(0.0, 1.0)
            delay = max(backoff, _retry_after(response.headers.get("Retry-After")))
            logger.warning("RETRY url=%s status=%s attempt=%s wait=%.3fs", url, status, attempt + 1, delay)
            await asyncio.sleep(delay)
        except (TimeoutError, httpx.TimeoutException, httpx.TransportError):
            if attempt == max(1, attempts) - 1:
                raise
            delay = min(8.0, 0.25 * 2**attempt) + random.uniform(0.0, 1.0)
            logger.warning("RETRY url=%s error=transport attempt=%s wait=%.3fs", url, attempt + 1, delay)
            await asyncio.sleep(delay)
    raise RuntimeError("Unexpected fetch state")
