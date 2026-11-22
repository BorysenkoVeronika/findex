"""Measure 20 overlapping requests for sync and async-offloaded search."""

import asyncio
from pathlib import Path
import statistics
import time

import httpx

from findex.store import load
from findex.web.app import app, get_index


async def measure(path: str, count: int = 20) -> tuple[float, float]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        start = time.perf_counter()
        responses = await asyncio.gather(*(client.get(path, params={"q": "python"}) for _ in range(count)))
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert all(r.status_code == 200 for r in responses)
        return elapsed_ms, statistics.median(float(r.json()["took_ms"]) for r in responses)


async def main() -> None:
    app.dependency_overrides[get_index] = lambda: load(Path("index.bin"))
    try:
        for route in ("/search", "/search-async"):
            elapsed, median_latency = await measure(route)
            print(f"{route}: 20 requests in {elapsed:.2f} ms; median handler {median_latency:.2f} ms")
    finally:
        app.dependency_overrides.clear()


if __name__ == "__main__":
    asyncio.run(main())
