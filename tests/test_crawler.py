"""Lab 06 network-free tests using httpx.MockTransport."""

from __future__ import annotations

import asyncio

import httpx

from findex.crawler.crawl import canonicalize, crawl
from findex.crawler.fetch import fetch
from findex.crawler.robots import RobotsCache


USER_AGENT = "FindexCrawler/0.6 (+https://example.test/contact)"


def test_fetch_does_not_retry_404() -> None:
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(404)

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            result = await fetch(client, "https://example.test/missing")
            assert result.status == 404

    asyncio.run(run())
    assert calls == 1


def test_fetch_retries_429() -> None:
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "0"}) if calls == 1 else httpx.Response(200, text="ok")

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            result = await fetch(client, "https://example.test/retry")
            assert result.status == 200

    asyncio.run(run())
    assert calls == 2


def test_robots_denies_disallowed_page() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="User-agent: *\nDisallow: /private\n")

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            robots = RobotsCache(client, USER_AGENT)
            assert not await robots.allowed("https://example.test/private")
            assert await robots.allowed("https://example.test/public")

    asyncio.run(run())


def test_crawl_deduplicates_and_limits_pages() -> None:
    requested: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        requested.append(request.url.path)
        html = '<html><title>Title</title><body><a href="/child#fragment">One</a><a href="/child">Two</a>Body</body></html>'
        return httpx.Response(200, text=html, headers={"Content-Type": "text/html"})

    async def run() -> list[str]:
        return [
            page.url
            async for page in crawl(
                ["https://example.test/"],
                max_pages=2,
                concurrency=2,
                per_host=2,
                min_host_delay=0,
                user_agent=USER_AGENT,
                transport=httpx.MockTransport(handle),
            )
        ]

    pages = asyncio.run(run())
    assert len(pages) == 2
    assert requested.count("/child") == 1
    assert canonicalize("HTTPS://Example.TEST/child/#x") == "https://example.test/child"
