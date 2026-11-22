"""Queue-frontier crawler with bounded structured concurrency."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
import logging
import time
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import httpx

from findex.crawler.fetch import fetch
from findex.crawler.robots import RobotsCache

logger = logging.getLogger("findex.crawler")


@dataclass(frozen=True, slots=True)
class Page:
    url: str
    title: str
    text: str
    fetched_at: str


@dataclass(frozen=True, slots=True)
class CrawlStats:
    pages: int
    errors: int
    in_flight: int
    queued: int


class _HTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.title: list[str] = []
        self.body: list[str] = []
        self._title = False
        self._hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._hidden += 1
        if tag == "title":
            self._title = True
        if tag == "a":
            self.links.extend(value for name, value in attrs if name == "href" and value)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"}:
            self._hidden = max(0, self._hidden - 1)
        if tag == "title":
            self._title = False

    def handle_data(self, data: str) -> None:
        if self._hidden:
            return
        if self._title:
            self.title.append(data)
        else:
            self.body.append(data)


def canonicalize(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        raise ValueError(f"Unsupported URL: {url}")
    hostname = parts.hostname.lower()
    if ":" in hostname:
        hostname = f"[{hostname}]"
    port = parts.port
    host = hostname + (f":{port}" if port and port != (443 if parts.scheme.lower() == "https" else 80) else "")
    path = parts.path.rstrip("/") or "/"
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    return urlunsplit((parts.scheme.lower(), host, path, query, ""))


async def crawl(
    seeds: Iterable[str],
    *,
    max_pages: int = 500,
    concurrency: int = 10,
    per_host: int = 2,
    allowed_domains: set[str] | None = None,
    min_host_delay: float = 0.2,
    user_agent: str,
    transport: httpx.AsyncBaseTransport | None = None,
    on_progress: Callable[[CrawlStats], None] | None = None,
) -> AsyncIterator[Page]:
    """Yield HTML pages as fetched; reserve at most max_pages unique URL attempts."""
    if max_pages <= 0:
        return
    if not user_agent.strip() or "http" not in user_agent:
        raise ValueError("Provide a truthful crawler User-Agent with a contact URL")
    concurrency = max(1, concurrency)
    per_host = max(1, per_host)
    seed_urls = [canonicalize(seed) for seed in seeds]
    domains = (
        {domain.lower() for domain in allowed_domains}
        if allowed_domains is not None
        else {urlsplit(seed).hostname or "" for seed in seed_urls}
    )
    frontier: asyncio.Queue[str] = asyncio.Queue()
    results: asyncio.Queue[Page | None] = asyncio.Queue()
    seen: set[str] = set()
    for seed in seed_urls:
        if urlsplit(seed).hostname in domains and seed not in seen:
            seen.add(seed)
            frontier.put_nowait(seed)

    host_limits: dict[str, asyncio.Semaphore] = defaultdict(lambda: asyncio.Semaphore(per_host))
    delay_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
    last_request: dict[str, float] = {}
    state_lock = asyncio.Lock()
    total_attempts = 0
    pages = 0
    errors = 0
    in_flight = 0
    total_limit = asyncio.Semaphore(concurrency)

    def publish() -> None:
        if on_progress is not None:
            on_progress(CrawlStats(pages, errors, in_flight, frontier.qsize()))

    async with httpx.AsyncClient(transport=transport, headers={"User-Agent": user_agent}) as client:
        robots = RobotsCache(client, user_agent)

        async def worker() -> None:
            nonlocal total_attempts, pages, errors, in_flight
            while True:
                url = await frontier.get()
                try:
                    async with state_lock:
                        if total_attempts >= max_pages:
                            continue
                        total_attempts += 1
                        in_flight += 1
                        publish()
                    host = urlsplit(url).netloc
                    async with total_limit, host_limits[host]:
                        async with delay_locks[host]:
                            wait = min_host_delay - (time.monotonic() - last_request.get(host, -1e12))
                            if wait > 0:
                                await asyncio.sleep(wait)
                            last_request[host] = time.monotonic()
                        if not await robots.allowed(url):
                            logger.info("ROBOTS_DENIED url=%s", url)
                            async with state_lock:
                                errors += 1
                            continue
                        response = await fetch(client, url)
                    logger.info(
                        "FETCH url=%s status=%d bytes=%d elapsed=%.3fs",
                        url,
                        response.status,
                        len(response.content),
                        response.elapsed,
                    )
                    if response.status != 200:
                        async with state_lock:
                            errors += 1
                        continue
                    if "html" not in response.content_type.lower() and b"<html" not in response.content[:1024].lower():
                        continue
                    parsed = _HTML()
                    parsed.feed(response.content.decode("utf-8", errors="replace"))
                    final_url = canonicalize(response.url)
                    if urlsplit(final_url).hostname not in domains:
                        logger.warning("REDIRECT_OUT_OF_SCOPE url=%s", response.url)
                        async with state_lock:
                            errors += 1
                        continue
                    page = Page(
                        final_url,
                        " ".join(" ".join(parsed.title).split()) or final_url,
                        " ".join(" ".join(parsed.body).split()),
                        datetime.now(timezone.utc).isoformat(),
                    )
                    async with state_lock:
                        pages += 1
                    await results.put(page)
                    for href in parsed.links:
                        try:
                            target = canonicalize(urljoin(final_url, href))
                        except ValueError:
                            continue
                        if urlsplit(target).hostname not in domains:
                            continue
                        async with state_lock:
                            if target not in seen and len(seen) < max_pages * 10:
                                seen.add(target)
                                frontier.put_nowait(target)
                except (httpx.HTTPError, TimeoutError, ValueError, UnicodeError) as exc:
                    logger.warning("FETCH_FAILED url=%s error=%s", url, exc)
                    async with state_lock:
                        errors += 1
                finally:
                    async with state_lock:
                        if in_flight:
                            in_flight -= 1
                        publish()
                    frontier.task_done()

        async with asyncio.TaskGroup() as group:
            workers = [group.create_task(worker()) for _ in range(concurrency)]

            async def finish() -> None:
                await frontier.join()
                await results.put(None)

            monitor = group.create_task(finish())
            try:
                while True:
                    item = await results.get()
                    if item is None:
                        break
                    yield item
            finally:
                monitor.cancel()
                for worker_task in workers:
                    worker_task.cancel()
