"""Synthetic traffic generator for the demo dashboard (several tenants, features and models)."""

from __future__ import annotations

import asyncio
import contextlib
import os
import random

import httpx

TENANTS = ("acme", "globex", "initech")
FEATURES = ("chat", "summarize", "classify")
PROMPT_WORDS = ("please", "summarize", "the", "quarterly", "report", "and", "list", "main", "risks")
LARGE_MODEL_SHARE = 0.25


async def worker(client: httpx.AsyncClient, rng: random.Random, rate_per_s: float) -> None:
    while True:
        tenant = rng.choice(TENANTS)
        payload = {
            "prompt": " ".join(rng.choices(PROMPT_WORDS, k=rng.randint(5, 200))),
            "model": "fake-large" if rng.random() < LARGE_MODEL_SHARE else "fake-small",
            "feature": rng.choice(FEATURES),
        }
        with contextlib.suppress(httpx.HTTPError):
            await client.post("/v1/chat", json=payload, headers={"x-tenant": tenant})
        await asyncio.sleep(rng.expovariate(rate_per_s))


async def main() -> None:
    base_url = os.getenv("TARGET_URL", "http://localhost:8000")
    workers = int(os.getenv("WORKERS", "4"))
    rate = float(os.getenv("RATE_PER_WORKER", "2"))
    rng = random.Random(int(os.getenv("SEED", "42")))
    async with httpx.AsyncClient(base_url=base_url, timeout=30) as client:
        await asyncio.gather(*(worker(client, rng, rate) for _ in range(workers)))


if __name__ == "__main__":
    asyncio.run(main())
