"""M4: reproducible 200-page in-memory crawler benchmark (no external traffic).

The synthetic transport models network waiting. Values are generated only when
this script is run; do not present them as real-site measurements.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import time
from pathlib import Path

import httpx
import psutil

from findex.crawler.crawl import CrawlStats, crawl


async def measure(pages: int, concurrency: int, latency: float) -> dict[str, float | int]:
    attempts: dict[str, int] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        await asyncio.sleep(latency)
        attempts[path] = attempts.get(path, 0) + 1
        if path == "/page/15" and attempts[path] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        links = "".join(f'<a href="/page/{i}">Page {i}</a>' for i in range(1, pages)) if path == "/" else ""
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            text=f"<html><title>{path}</title><body>Example {links}</body></html>",
        )

    progress = CrawlStats(0, 0, 0, 0)

    def update(stats: CrawlStats) -> None:
        nonlocal progress
        progress = stats

    peak_rss = psutil.Process().memory_info().rss
    started = time.perf_counter()
    count = 0
    async for _ in crawl(
        ["https://example.test/"],
        max_pages=pages,
        concurrency=concurrency,
        per_host=concurrency,
        min_host_delay=0.0,
        user_agent="FindexCrawler/0.6 (+https://example.test/contact)",
        transport=httpx.MockTransport(handler),
        on_progress=update,
    ):
        count += 1
        peak_rss = max(peak_rss, psutil.Process().memory_info().rss)
    elapsed = time.perf_counter() - started
    return {
        "concurrency": concurrency,
        "pages": count,
        "wall_s": round(elapsed, 4),
        "pages_per_s": round(count / elapsed, 2),
        "errors": progress.errors,
        "peak_rss_mib": round(peak_rss / 1048576, 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", type=int, default=200)
    parser.add_argument("--latency", type=float, default=0.02)
    args = parser.parse_args()
    if args.pages < 200:
        parser.error("M4 requires at least 200 pages")
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    rows = [asyncio.run(measure(args.pages, n, args.latency)) for n in (1, 5, 20)]
    Path("docs").mkdir(exist_ok=True)
    with Path("docs/lab06-benchmark.csv").open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    for row in rows:
        print(row)
    print("Saved docs/lab06-benchmark.csv")


if __name__ == "__main__":
    main()
