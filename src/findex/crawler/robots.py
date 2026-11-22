"""Host-scoped robots.txt policies with safe, concurrent caching."""

from __future__ import annotations

import asyncio
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx


class RobotsCache:
    def __init__(self, client: httpx.AsyncClient, user_agent: str) -> None:
        self.client = client
        self.user_agent = user_agent
        self._policies: dict[str, RobotFileParser | None] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        host = f"{parts.scheme}://{parts.netloc}"
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            if host not in self._policies:
                try:
                    async with asyncio.timeout(10.0):
                        result = await self.client.get(f"{host}/robots.txt", follow_redirects=False)
                    if result.status_code in (404, 410):
                        self._policies[host] = None
                    elif result.status_code == 200:
                        policy = RobotFileParser()
                        policy.parse(result.text.splitlines())
                        self._policies[host] = policy
                    else:
                        return False  # Fail closed for unknown policies.
                except (httpx.HTTPError, TimeoutError):
                    return False
            policy = self._policies[host]
        return policy is None or policy.can_fetch(self.user_agent, url)
